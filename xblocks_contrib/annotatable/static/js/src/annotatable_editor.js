function XMLEditingDescriptor(runtime, element) {
    var saveButtonSelector = '.save-button';
    var cancelButtonSelector = '.cancel-button';
    var editBoxSelector = '.edit-box';
    var _debug = false;

    var el = element;

    var textarea = $(editBoxSelector, el)[0];
    if (!textarea) {
        console.error('Error: Textarea with class "edit-box" not found.');
        return;
    }

    var editBox = CodeMirror.fromTextArea(textarea, {
        mode: 'xml',
        lineNumbers: true,
        lineWrapping: true
    });

    if (_debug) {
        console.log('loaded XMLEditingDescriptor');
    }

    function init() {
        initEvents();
    }

    function initEvents() {
        $(saveButtonSelector, el).on('click', onClickSave);
        $(cancelButtonSelector, el).on('click', onClickCancel);
    }

    function onClickSave(e) {
        e.preventDefault();
        submit();
    }

    function onClickCancel(e) {
        e.preventDefault();
        closeEditor();
    }

    function save() {
        return {
            data: editBox.getValue()
        };
    }

    function submit() {
        var handlerUrl = runtime.handlerUrl(el, 'submit_studio_edits');
        runtime.notify('save', {state: 'start', message: 'Saving...'});
        var data = save();

        $.ajax({
            type: 'POST',
            url: handlerUrl,
            data: JSON.stringify(data),
            dataType: 'json',
            success: function(response) {
                runtime.notify('save', {state: 'end'});
            }
        }).fail(function(jqXHR) {
            var message = 'There was an issue saving the settings. Please try again.';
            runtime.notify('error', {title: 'Unable to save', message: message});
        });
    }

    function closeEditor() {
        runtime.notify('cancel', {});
    }

    init();
}
