
/* JavaScript for ProblemBlock. */
function ProblemBlock(runtime, element) {
    const updateCount = (result) => {
        $('.count', element).text(result.count);
    };

    const handlerUrl = runtime.handlerUrl(element, 'increment_count');

    $('p', element).on('click', (eventObject) => {
        $.ajax({
            type: 'POST',
            url: handlerUrl,
            contentType: 'application/json',
            data: JSON.stringify({hello: 'world'}),
            success: updateCount
        });
    });

    $(() => {
        /*
        Use `gettext` provided by django-statici18n for static translations
        */

        // eslint-disable-next-line no-undef
        const dummyText = gettext('Hello World');

        // Example usage of interpolation for translated strings
        // eslint-disable-next-line no-undef
        const message = StringUtils.interpolate(
            gettext('You are enrolling in {courseName}'),
            {
                courseName: 'Rock & Roll 101'
            }
        );
        console.log(message); // This is just for demonstration purposes
    });
}
