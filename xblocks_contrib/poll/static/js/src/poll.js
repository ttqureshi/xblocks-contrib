function PollBlock(runtime, element) {
    const questionEl = $(element).find('.poll_question');

    if (questionEl.length !== 1) {
        console.log('ERROR: PollBlock requires exactly one .poll_question element.');
        return;
    }

    if (questionEl.attr('poll_main_processed') === 'true') {
        console.log('PollBlock already initialized for this element.');
        return;
    }

    questionEl.attr('poll_main_processed', 'true');

    // Local variables scoped to this PollBlock instance
    let jsonConfig = {};
    let id = null;
    let answersObj = {};
    let questionAnswered = false;
    let canReset = false;
    let resetButton = null;
    let wrapperSectionEl = null;
    let shortVersion = true;

    // Helper: finds parent wrapper
    (function findWrapper(tempEl, counter) {
        while (tempEl.tagName.toLowerCase() !== 'body' && counter <= 50) {
            tempEl = $(tempEl).parent()[0];
            counter++;
            if ($(tempEl).data('block-type') === 'wrapper') {
                wrapperSectionEl = tempEl;
                break;
            }
        }
    })($(element)[0], 0);

    // HTML escaping helper (use this until you add the real HtmlUtils)
    const HTML = function (str) {
        return {
            toString: function () {
                return $('<div/>').text(str).html();
            }
        };
    };

    function renderQuestion() {
        id = questionEl.attr('id');
        questionEl.append(jsonConfig.question);

        answersObj = {};
        shortVersion = true;

        $.each(jsonConfig.answers, function (index, value) {
            if (value.length >= 18) shortVersion = false;
        });

        $.each(jsonConfig.answers, function (index, value) {
                const answer = {};
                answersObj[index] = answer;

                answer.el = $('<div class="poll_answer"></div>');
                answer.questionEl = $('<div class="question"></div>');
                answer.buttonEl = $('<div class="button"></div>');

                answer.textEl = $('<div class="text"></div>').html(value);

                answer.questionEl.append(answer.buttonEl).append(answer.textEl);
                answer.el.append(answer.questionEl);

                answer.statsEl = $('<div class="stats"></div>').hide();
                answer.barEl = $('<div class="bar"></div>');
                answer.percentEl = $('<div class="percent"></div>');
                answer.barEl.append(answer.percentEl);
                answer.numberEl = $('<div class="number"></div>');

                answer.statsEl.append(answer.barEl).append(answer.numberEl);
                answer.el.append(answer.statsEl);

                if (shortVersion) {
                    $.each(answer, function (k, v) {
                        if (v instanceof jQuery) v.addClass('short');
                    });
                }

                answer.el.appendTo(questionEl);

                answer.textEl.on('click', () => submitAnswer(index, answer));
                answer.buttonEl.on('click', () => submitAnswer(index, answer));

                if (index === jsonConfig.poll_answer) {
                    answer.buttonEl.addClass('answered');
                    questionAnswered = true;
                }
            });

        if (jsonConfig.reset?.toLowerCase() === 'true') {
            canReset = true;
            resetButton = $('<div class="button reset-button">Change your vote</div>');
            if (!questionAnswered) resetButton.hide();
            questionEl.append(resetButton);
            resetButton.on('click', submitReset);
        }

        if (questionAnswered) {
            showAnswerGraph(jsonConfig.poll_answers, jsonConfig.total);
        }
    }

    function showAnswerGraph(poll_answers, total) {
        const totalValue = parseFloat(total);
        if (!isFinite(totalValue)) return;

        $.each(poll_answers, function (index, value) {
            const numValue = parseFloat(value);
            if (!isFinite(numValue)) return;

            const percentValue = (numValue / totalValue) * 100.0;
            const answer = answersObj[index];
            answer.statsEl.show();
            answer.numberEl.html(`${value} (${percentValue.toFixed(1)}%)`);
            answer.percentEl.css({ width: `${percentValue.toFixed(1)}%` });
        });
    }

    function submitAnswer(index, answerObj) {
        if (questionAnswered) return;
        questionAnswered = true;

        answerObj.buttonEl.addClass('answered');

        $.ajax({
            type: 'POST',
            url: runtime.handlerUrl(element, 'handle_submit_state'),
            data: JSON.stringify({ answer: index }),
            success: function (response) {
                showAnswerGraph(response.poll_answers, response.total);
                if (canReset && resetButton) resetButton.show();

                if (wrapperSectionEl) {
                    $(wrapperSectionEl).find('.xmodule_ConditionalModule').each(function (i, val) {
                        // eslint-disable-next-line no-new
                        new window.Conditional(val, runtime, id.replace(/^poll_/, ''));
                    });
                }
            }
        });
    }

    function submitReset() {
        $.ajax({
            type: 'POST',
            url: runtime.handlerUrl(element, 'handle_reset_state'),
            data: JSON.stringify({}),
            success: function (response) {
                if (response.status?.toLowerCase() !== 'success') return;

                questionAnswered = false;
                questionEl.find('.button.answered').removeClass('answered');
                questionEl.find('.stats').hide();
                if (resetButton) resetButton.hide();

                if (wrapperSectionEl) {
                    $(wrapperSectionEl).find('.xmodule_ConditionalModule').each(function (i, val) {
                        // eslint-disable-next-line no-new
                        new window.Conditional(val, runtime, id.replace(/^poll_/, ''));
                    });
                }
            }
        });
    }

    // Start execution: get state, then initialize
    try {
        jsonConfig = JSON.parse(questionEl.children('.poll_question_div').html());

        $.ajax({
            type: 'POST',
            url: runtime.handlerUrl(element, 'handle_get_state'),
            data: JSON.stringify(null),
            success: function (response) {
                jsonConfig.poll_answer = response.poll_answer;
                jsonConfig.total = response.total;

                $.each(response.poll_answers, function (index, value) {
                    jsonConfig.poll_answers[index] = value;
                });

                questionEl.children('.poll_question_div').html(JSON.stringify(jsonConfig));
                renderQuestion();
            }
        });
    } catch (err) {
        console.log('ERROR: Invalid JSON config.', err.message);
    }
}
