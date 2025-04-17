function Annotatable(runtime, element) {
    var _debug = false;

    /*
    Selectors for the annotatable xmodule
    */
    var wrapperSelector = '.annotatable-wrapper';
    var toggleAnnotationsSelector = '.annotatable-toggle-annotations';
    var toggleInstructionsSelector = '.annotatable-toggle-instructions';
    var instructionsSelector = '.annotatable-instructions';
    var spanSelector = '.annotatable-span';
    var replySelector = '.annotatable-reply';

    /*
    Selectors for responding to events from the annotation capa problem type
    */
    var problemInputSelector = 'div.problem .annotation-input';
    var problemReturnSelector = 'div.problem .annotation-return';

    var annotationsHidden = false;
    var instructionsHidden = false;

    var $el = $(element);

    init();

    function init() {
        initEvents();
        initTips();
        if (_debug) {
            console.log('Annotatable XBlock Loaded');
        }
    }

    function initEvents() {
        annotationsHidden = false;
        instructionsHidden = false;

        /*
        Initialize toggle handlers for the instructions and annotations sections
        */
        $(toggleAnnotationsSelector).on('click', onClickToggleAnnotations);
        $(toggleInstructionsSelector).on('click', onClickToggleInstructions);

        /*
        Initialize handler for 'reply to annotation' events that scroll to
        the associated problem. The reply buttons are part of the tooltip
        content. It's important that the tooltips be configured to render
        as descendants of the annotation module and *not* the document.body.
        */
        $el.on('click', replySelector, onClickReply);

        /*
      Initialize handler for 'return to annotation' events triggered from problems.
        1) There are annotationinput capa problems rendered on the page
        2) Each one has an embedded return link (see annotation capa problem template).
      Since the capa problem injects HTML content via AJAX, the best we can do is
      let the click events bubble up to the body and handle them there.
      */
        $(document).on('click', problemReturnSelector, onClickReturn);
    }

    function initTips() {
        /*
        Tooltips are used to display annotations for highlighted text spans
        */
        $(spanSelector).each(function(index, el) {
            $(el).qtip(getSpanTipOptions(el));
        });
    }

    function getSpanTipOptions(el) {
        return {
            content: {
                title: {
                    text: makeTipTitle(el),
                },
                text: makeTipContent(el),
            },
            position: {
                /*
                Of tooltip
                */
                my: 'bottom center',
                /*
                Of target
                */
                at: 'top center',
                /*
                Where the tooltip was triggered (i.e., the annotation span)
                */
                target: $(el),
                container: $(wrapperSelector),
                adjust: {
                    y: -5,
                },
            },
            show: {
                event: 'click mouseenter',
                solo: true,
            },
            hide: {
                event: 'click mouseleave',
                delay: 500,
                /*
                Don't hide the tooltip if it is moused over
                */
                fixed: true,
            },
            style: {
                classes: 'ui-tooltip-annotatable',
            },
            events: {
                show: onShowTip,
                move: onMoveTip,
            },
        };
    }

    function onClickToggleAnnotations(e) {
        toggleAnnotations();
    }

    function onClickToggleInstructions(e) {
        toggleInstructions();
    }

    function onClickReply(e) {
        replyTo(e.currentTarget);
    }

    function onClickReturn(e) {
        returnFrom(e.currentTarget);
    }

    function onShowTip(event, api) {
        if (annotationsHidden) {
            event.preventDefault();
        }
    }

    function onMoveTip(event, api, position) {
        /*
      This method handles a vertical positioning bug in Firefox as
      well as an edge case in which a tooltip is displayed above a
      non-overlapping span like this:

                           (( TOOLTIP ))
                                \/
      text text text ... text text text ...... <span span span>
      <span span span>

      The problem is that the tooltip looks disconnected from both spans, so
      we should re-position the tooltip to appear above the span.
      */
        var tip = api.elements.tooltip;
        var adjustY = (api.options.position && api.options.position.adjust && api.options.position.adjust.y) || 0;
        var container = (api.options.position && api.options.position.container) || $('body');
        var target = api.elements.target;
        var rects = $(target).get(0).getClientRects();
        var isNonOverlapping = rects && rects.length === 2 && rects[0].left > rects[1].right;
        var focusRect;

        if (isNonOverlapping) {
            /*
            Choose the largest of the two non-overlapping spans and display
            the tooltip above the center of it
            */
            focusRect = rects[0].width > rects[1].width ? rects[0] : rects[1];
        } else {
            /*
            Always compute the new position because Firefox doesn't
            properly vertically position the tooltip
            */
            focusRect = rects[0];
        }

        var rectCenter = focusRect.left + focusRect.width / 2;
        var rectTop = focusRect.top;
        var tipWidth = $(tip).width();
        var tipHeight = $(tip).height();

        /*
        Tooltip is positioned relative to its container, so we need to factor in offsets
        */
        var containerOffset = $(container).offset();
        var offsetLeft = -containerOffset.left;
        var offsetTop = $(document).scrollTop() - containerOffset.top;
        var tipLeft = offsetLeft + rectCenter - tipWidth / 2;
        var tipTop = offsetTop + rectTop - tipHeight + adjustY;

        /*
        Make sure the new tip position doesn't clip the edges of the screen
        */
        var winWidth = $(window).width();
        if (tipLeft < offsetLeft) {
            tipLeft = offsetLeft;
        } else if (tipLeft + tipWidth > winWidth + offsetLeft) {
            tipLeft = winWidth + offsetLeft - tipWidth;
        }

        /*
        Update the position object (used by qTip2 to show the tip after the move event)
        */
        $.extend(position, {
            left: tipLeft,
            top: tipTop,
        });
    }

    function getSpanForProblemReturn(el) {
        var problemId = $(problemReturnSelector).index(el);
        return $(spanSelector).filter("[data-problem-id='" + problemId + "']");
    }

    function getProblem(el) {
        var problemId = getProblemId(el);
        return $(problemInputSelector).eq(problemId);
    }

    function getProblemId(el) {
        return $(el).data('problem-id');
    }

    function toggleAnnotations() {
        annotationsHidden = !annotationsHidden;
        var hide = annotationsHidden;
        toggleAnnotationButtonText(hide);
        toggleSpans(hide);
        toggleTips(hide);
    }

    function toggleTips(hide) {
        var visible = findVisibleTips();
        hideTips(visible);
    }

    function toggleAnnotationButtonText(hide) {
        var buttonText = hide ? gettext('Show Annotations') : gettext('Hide Annotations');
        $(toggleAnnotationsSelector).text(buttonText);
    }

    function toggleInstructions() {
        instructionsHidden = !instructionsHidden;
        var hide = instructionsHidden;
        toggleInstructionsButton(hide);
        toggleInstructionsText(hide);
    }

    function toggleInstructionsButton(hide) {
        var txt = hide ? gettext('Expand Instructions') : gettext('Collapse Instructions');
        var cls = hide ? ['expanded', 'collapsed'] : ['collapsed', 'expanded'];
        $(toggleInstructionsSelector).text(txt).removeClass(cls[0]).addClass(cls[1]);
    }

    function toggleInstructionsText(hide) {
        var slideMethod = hide ? 'slideUp' : 'slideDown';
        $(instructionsSelector)[slideMethod]();
    }

    function toggleSpans(hide) {
        $(spanSelector).toggleClass('hide', hide, 250);
    }

    function replyTo(buttonEl) {
        var offset = -20;
        var el = getProblem(buttonEl);
        if (el.length > 0) {
            scrollTo(el, afterScrollToProblem, offset);
        } else if (_debug) {
            console.log('Problem not found. Element:', buttonEl);
        }
    }

    function returnFrom(buttonEl) {
        var offset = -200;
        var el = getSpanForProblemReturn(buttonEl);
        if (el.length > 0) {
            scrollTo(el, afterScrollToSpan, offset);
        } else if (_debug) {
            console.log('Span not found. Element:', buttonEl);
        }
    }

    function scrollTo(el, after, offset) {
        offset = offset || -20;
        if ($(el).length > 0) {
            $('html,body').scrollTo(el, {
                duration: 500,
                onAfter: _once(function() {
                    if (after) {
                        after.call(this, el);
                    }
                }),
                offset: offset,
            });
        }
    }

    function afterScrollToProblem(problemEl) {
        problemEl.effect('highlight', {}, 500);
    }

    function afterScrollToSpan(spanEl) {
        spanEl.addClass('selected', 400, 'swing', function() {
            spanEl.removeClass('selected', 400, 'swing');
        });
    }

    function makeTipContent(el) {
        return function(api) {
            var text = $(el).data('comment-body');
            var comment = createComment(text);
            var problemId = getProblemId(el);
            var reply = createReplyLink(problemId);
            return $(comment).add(reply);
        };
    }

    function makeTipTitle(el) {
        return function(api) {
            var title = $(el).data('comment-title');
            return title || gettext('Commentary');
        };
    }

    function createComment(text) {
        return $('<div class="annotatable-comment">' + text + '</div>'); // xss-lint: disable=javascript-concat-html
    }

    function createReplyLink(problemId) {
        var linkText = gettext('Reply to Annotation');
        return $(
            '<a class="annotatable-reply" href="javascript:void(0);" data-problem-id="'
            + problemId
            + '">'
            + linkText
            + '</a>',
        ); // xss-lint: disable=javascript-concat-html
    }

    function findVisibleTips() {
        var visible = [];
        $(spanSelector).each(function(index, el) {
            var api = $(el).qtip('api');
            var tip = $(api && api.elements.tooltip);
            if (tip.is(':visible')) {
                visible.push(el);
            }
        });
        return visible;
    }

    function hideTips(elements) {
        $(elements).qtip('hide');
    }

    function _once(fn) {
        var done = false;
        return function() {
            if (!done) {
                fn.call(this);
                done = true;
            }
        };
    }
}
