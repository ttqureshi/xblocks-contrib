/* JavaScript for LTIBlock. */

function LTIBlock(runtime, element) {
    'use strict';

    const $lti = $(element).find('.lti');
    const askToSendUsername = $lti.data('ask-to-send-username') === 'True';
    const askToSendEmail = $lti.data('ask-to-send-email') === 'True';

    // When the lti button is clicked, provide users the option to
    // accept or reject sending their information to a third party
    $(element).on('click', '.link_lti_new_window', function() {
        if (askToSendUsername && askToSendEmail) {
            return confirm('Click OK to have your username and e-mail address sent to a 3rd party application.\n\nClick Cancel to return to this page without sending your information.');
        } else if (askToSendUsername) {
            return confirm('Click OK to have your username sent to a 3rd party application.\n\nClick Cancel to return to this page without sending your information.');
        } else if (askToSendEmail) {
            return confirm('Click OK to have your e-mail address sent to a 3rd party application.\n\nClick Cancel to return to this page without sending your information.');
        } else {
            return true;
        }
    });
}
