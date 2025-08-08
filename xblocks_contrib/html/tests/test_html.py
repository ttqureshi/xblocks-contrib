import unittest
from unittest.mock import Mock

import ddt
from django.contrib.auth.models import AnonymousUser
from django.test.utils import override_settings
from opaque_keys.edx.locator import BlockUsageLocator, CourseLocator
from xblock.field_data import DictFieldData
from xblock.fields import ScopeIds
from xblock.reference.user_service import UserService, XBlockUser
from xblock.test.tools import TestRuntime

from xblocks_contrib.html.html import HtmlBlock


def get_test_descriptor_system():
    """
    Construct a minimal test descriptor system for XBlocks.
    """
    return TestRuntime(services={})


def get_test_system(
    course_id=CourseLocator("org", "course", "run"),
    user=None,
    user_is_staff=False,
    user_location=None,
    render_template=None,
    add_get_block_overrides=False,
):
    """
    Construct a test system instance for the HTML XBlock.

    By default, the system's render_template() method simply returns the repr of the
    context it is passed. You can override this by passing in a different render_template argument.
    """

    if not user:
        user = Mock(name="get_test_system.user", is_staff=False)
    if not user_location:
        user_location = Mock(name="get_test_system.user_location")

    class StubUserService(UserService):
        """
        Stub UserService for testing the sequence block.
        """

        def __init__(self, user=None, anonymous_user_id=None, deprecated_anonymous_user_id=None, **kwargs):
            self.user = user
            self.anonymous_user_id = anonymous_user_id
            self.deprecated_anonymous_user_id = deprecated_anonymous_user_id
            super().__init__(**kwargs)

        def get_current_user(self):
            """
            Implements abstract method for getting the current user.
            """
            user = XBlockUser()
            if self.user and self.user.is_authenticated:
                user.opt_attrs["edx-platform.anonymous_user_id"] = self.anonymous_user_id
                user.opt_attrs["edx-platform.deprecated_anonymous_user_id"] = self.deprecated_anonymous_user_id

            return user

    class TestRuntimeWithRender(TestRuntime):
        """Custom runtime that includes a basic render method."""

        def __init__(self, services, anonymous_student_id="test-user-id"):
            super().__init__(services=services)
            self.anonymous_student_id = anonymous_student_id

        def render(self, block, view, context):
            return Mock(content=block.get_html())

    services = {
        "user": StubUserService(
            user=user,
            anonymous_user_id="test-user-id",
            deprecated_anonymous_user_id="test-user-id",
        ),
    }

    return TestRuntimeWithRender(services=services)


def instantiate_block(**field_data):
    """
    Instantiate block with most properties.
    """
    system = get_test_descriptor_system()
    course_key = CourseLocator("org", "course", "run")
    usage_key = course_key.make_usage_key("html", "SampleHtml")
    return system.construct_xblock_from_class(
        HtmlBlock,
        scope_ids=ScopeIds(None, None, usage_key, usage_key),
        field_data=DictFieldData(field_data),
    )


@ddt.ddt
class HtmlBlockCourseApiTestCase(unittest.TestCase):
    """
    Test the HTML XModule's student_view_data method.
    """

    @ddt.data({}, dict(FEATURES={}), dict(FEATURES=dict(ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA=False)))
    def test_disabled(self, settings):
        """
        Ensure that student_view_data does not return html if the ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA feature flag
        is not set.
        """
        field_data = DictFieldData({"data": "<h1>Some HTML</h1>"})
        module_system = get_test_system()
        block = HtmlBlock(module_system, field_data, Mock())

        with override_settings(**settings):
            assert block.student_view_data() == dict(
                enabled=False, message='To enable, set FEATURES["ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA"]'
            )

    @ddt.data(
        "<h1>Some content</h1>",  # Valid HTML
        "",
        None,
        "<h1>Some content</h",  # Invalid HTML
        "<script>alert()</script>",  # Does not escape tags
        '<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">',  # Images allowed
        "short string " * 100,  # May contain long strings
    )
    @override_settings(FEATURES=dict(ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA=True))
    def test_common_values(self, html):
        """
        Ensure that student_view_data will return HTML data when enabled,
        can handle likely input,
        and doesn't modify the HTML in any way.

        This means that it does NOT protect against XSS, escape HTML tags, etc.

        Note that the %%USER_ID%% substitution is tested below.
        """
        field_data = DictFieldData({"data": html})
        module_system = get_test_system()
        block = HtmlBlock(module_system, field_data, Mock())
        assert block.student_view_data() == dict(enabled=True, html=html)

    @ddt.data("student_view")
    def test_student_preview_view(self, view):
        """
        Ensure that student_view and public_view renders correctly.
        """
        html = "<p>This is a test</p>"
        field_data = DictFieldData({"data": html})
        module_system = get_test_system()
        block = HtmlBlock(module_system, field_data, Mock())
        rendered = module_system.render(block, view, {}).content
        assert html in rendered


class HtmlBlockSubstitutionTestCase(unittest.TestCase):

    def test_substitution_user_id(self):
        sample_xml = """%%USER_ID%%"""
        field_data = DictFieldData({"data": sample_xml})
        module_system = get_test_system()
        block = HtmlBlock(module_system, field_data, Mock())
        assert block.get_html() == str(module_system.anonymous_student_id)

    def test_substitution_course_id(self):
        sample_xml = """%%COURSE_ID%%"""
        field_data = DictFieldData({"data": sample_xml})
        module_system = get_test_system()
        block = HtmlBlock(module_system, field_data, Mock())
        course_key = CourseLocator(org="some_org", course="some_course", run="some_run")
        usage_key = BlockUsageLocator(course_key=course_key, block_type="problem", block_id="block_id")
        block.scope_ids.usage_id = usage_key
        assert block.get_html() == str(course_key)

    def test_substitution_without_magic_string(self):
        sample_xml = """
            <html>
                <p>Hi USER_ID!11!</p>
            </html>
        """
        field_data = DictFieldData({"data": sample_xml})
        module_system = get_test_system()
        block = HtmlBlock(module_system, field_data, Mock())
        assert block.get_html() == sample_xml

    def test_substitution_without_anonymous_student_id(self):
        sample_xml = """%%USER_ID%%"""
        field_data = DictFieldData({"data": sample_xml})
        module_system = get_test_system(user=AnonymousUser())
        block = HtmlBlock(module_system, field_data, Mock())
        block.runtime.service(block, "user")._deprecated_anonymous_user_id = ""
        assert block.get_html() == sample_xml


class HtmlBlockIndexingTestCase(unittest.TestCase):
    """
    Make sure that HtmlBlock can format data for indexing as expected.
    """

    def test_index_dictionary_simple_html_block(self):
        sample_xml = """
            <html>
                <p>Hello World!</p>
            </html>
        """
        block = instantiate_block(data=sample_xml)
        assert block.index_dictionary() == {
            "content": {"html_content": " Hello World! ", "display_name": "Text"},
            "content_type": "Text",
        }

    def test_index_dictionary_cdata_html_block(self):
        sample_xml_cdata = """
            <html>
                <p>This has CDATA in it.</p>
                <![CDATA[This is just a CDATA!]]>
            </html>
        """
        block = instantiate_block(data=sample_xml_cdata)
        assert block.index_dictionary() == {
            "content": {"html_content": " This has CDATA in it. ", "display_name": "Text"},
            "content_type": "Text",
        }

    def test_index_dictionary_multiple_spaces_html_block(self):
        sample_xml_tab_spaces = """
            <html>
                <p>     Text has spaces :)  </p>
            </html>
        """
        block = instantiate_block(data=sample_xml_tab_spaces)
        assert block.index_dictionary() == {
            "content": {"html_content": " Text has spaces :) ", "display_name": "Text"},
            "content_type": "Text",
        }

    def test_index_dictionary_html_block_with_comment(self):
        sample_xml_comment = """
            <html>
                <p>This has HTML comment in it.</p>
                <!-- Html Comment -->
            </html>
        """
        block = instantiate_block(data=sample_xml_comment)
        assert block.index_dictionary() == {
            "content": {"html_content": " This has HTML comment in it. ", "display_name": "Text"},
            "content_type": "Text",
        }

    def test_index_dictionary_html_block_with_both_comments_and_cdata(self):
        sample_xml_mix_comment_cdata = """
            <html>
                <!-- Beginning of the html -->
                <p>This has HTML comment in it.<!-- Commenting Content --></p>
                <!-- Here comes CDATA -->
                <![CDATA[This is just a CDATA!]]>
                <p>HTML end.</p>
            </html>
        """
        block = instantiate_block(data=sample_xml_mix_comment_cdata)
        assert block.index_dictionary() == {
            "content": {"html_content": " This has HTML comment in it. HTML end. ", "display_name": "Text"},
            "content_type": "Text",
        }

    def test_index_dictionary_html_block_with_script_and_style_tags(self):
        sample_xml_style_script_tags = """
            <html>
                <style>p {color: green;}</style>
                <!-- Beginning of the html -->
                <p>This has HTML comment in it.<!-- Commenting Content --></p>
                <!-- Here comes CDATA -->
                <![CDATA[This is just a CDATA!]]>
                <p>HTML end.</p>
                <script>
                    var message = "Hello world!"
                </script>
            </html>
        """
        block = instantiate_block(data=sample_xml_style_script_tags)
        assert block.index_dictionary() == {
            "content": {"html_content": " This has HTML comment in it. HTML end. ", "display_name": "Text"},
            "content_type": "Text",
        }
