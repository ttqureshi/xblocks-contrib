"""
HTML XBlock module for displaying raw HTML content.
This XBlock allows users to embed HTML content inside courses.
"""

import copy
import datetime
import json
import logging
import os
import re
import sys
import uuid
from html.parser import HTMLParser

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.translation import gettext_noop as _
from fs.errors import ResourceNotFound
from lxml import etree
from lxml.etree import ElementTree, XMLParser
from opaque_keys.edx.keys import CourseKey, UsageKey
from opaque_keys.edx.locator import LibraryLocatorV2
from path import Path as path
from web_fragments.fragment import Fragment
from xblock.core import XML_NAMESPACES, XBlock
from xblock.fields import Boolean, Dict, Scope, ScopeIds, String, UserScope
from xblock.utils.resources import ResourceLoader

log = logging.getLogger(__name__)
resource_loader = ResourceLoader(__name__)

# The global (course-agnostic) anonymous user ID for the user.
ATTR_KEY_DEPRECATED_ANONYMOUS_USER_ID = "edx-platform.deprecated_anonymous_user_id"

# assume all XML files are persisted as utf-8.
EDX_XML_PARSER = XMLParser(dtd_validation=False, load_dtd=False, remove_blank_text=True, encoding="utf-8")


class EdxJSONEncoder(DjangoJSONEncoder):
    """
    Custom JSONEncoder that handles ``Location`` and ``datetime.datetime`` objects.
    Encodes ``Location`` as its URL string form, and ``datetime.datetime`` as an ISO 8601 string.
    """

    def default(self, o):
        if isinstance(o, (CourseKey, UsageKey)):
            return str(o)
        elif isinstance(o, datetime.datetime):
            if o.tzinfo is not None:
                if o.utcoffset() is None:
                    return o.isoformat() + "Z"
                else:
                    return o.isoformat()
            else:
                return o.isoformat()
        else:
            return super().default(o)


class MLStripper(HTMLParser):
    "helper function for html_to_text below"

    def __init__(self):
        HTMLParser.__init__(self)
        self.reset()
        self.fed = []

    def handle_starttag(self, tag, attrs):
        if tag != "img":
            return
        for attr in attrs:
            if len(attr) >= 2 and attr[0] == "alt":
                self.fed.append(attr[1])

    def handle_data(self, data):
        """takes the data in separate chunks"""
        self.fed.append(data)

    def handle_entityref(self, name):
        """appends the reference to the body"""
        self.fed.append("&%s;" % name)

    def get_data(self):
        """joins together the seperate chunks into one cohesive string"""
        return "".join(self.fed)


def html_to_text(html):
    """Convert HTML to plain text."""
    htmlstripper = MLStripper()
    htmlstripper.feed(html)
    return htmlstripper.get_data()


def escape_html_characters(content):
    """
    Remove HTML characters that shouldn't be indexed using ElasticSearch indexer
    This method is complementary to html_to_text method found in xmodule/annotator_mixin.py

    Args:
        content (str): variable to escape html characters from

    Returns:
        content (str): content ready to be index by ElasticSearch

    """

    # Removing HTML comments
    return re.sub(
        r"<!--.*-->",
        "",
        # Removing HTML CDATA
        re.sub(
            r"<!\[CDATA\[.*\]\]>",
            "",
            # Removing HTML-encoded non-breaking space characters
            re.sub(r"(\s|&nbsp;|//)+", " ", html_to_text(content)),
        ),
    )


def check_html(html):
    """
    Check whether the passed in html string can be parsed by lxml.
    Return bool success.
    """
    parser = etree.HTMLParser()
    try:
        etree.fromstring(html, parser)
        return True
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    return False


def stringify_children(node):
    """
    Return all contents of an xml tree, without the outside tags.
    e.g. if node is parse of

        "<html a="b" foo="bar">Hi <div>there <span>Bruce</span><b>!</b></div><html>"

    should return

        "Hi <div>there <span>Bruce</span><b>!</b></div>"

    fixed from
    http://stackoverflow.com/questions/4624062/get-all-text-inside-a-tag-in-lxml
    """
    # Useful things to know:

    # node.tostring() -- generates xml for the node, including start
    #                 and end tags.  We'll use this for the children.
    # node.text -- the text after the end of a start tag to the start
    #                 of the first child
    # node.tail -- the text after the end this tag to the start of the
    #                 next element.
    parts = [node.text]
    for c in node.getchildren():
        parts.append(etree.tostring(c, with_tail=True, encoding="unicode"))

    # filter removes possible Nones in texts and tails
    return "".join([part for part in parts if part])


def name_to_pathname(name):
    """
    Convert a location name for use in a path: replace ':' with '/'.
    This allows users of the xml format to organize content into directories
    """
    return name.replace(":", "/")


def is_pointer_tag(xml_obj):
    """
    Check if xml_obj is a pointer tag: <blah url_name="something" />.
    No children, one attribute named url_name, no text.

    Special case for course roots: the pointer is
      <course url_name="something" org="myorg" course="course">

    xml_obj: an etree Element

    Returns a bool.
    """
    if xml_obj.tag != "course":
        expected_attr = {"url_name"}
    else:
        expected_attr = {"url_name", "course", "org"}

    actual_attr = set(xml_obj.attrib.keys())

    has_text = xml_obj.text is not None and len(xml_obj.text.strip()) > 0

    return len(xml_obj) == 0 and actual_attr == expected_attr and not has_text


def serialize_field(value):
    """
    Return a string version of the value (where value is the JSON-formatted, internally stored value).

    If the value is a string, then we simply return what was passed in.
    Otherwise, we return json.dumps on the input value.
    """
    if isinstance(value, str):
        return value
    elif isinstance(value, datetime.datetime):
        if value.tzinfo is not None and value.utcoffset() is None:
            return value.isoformat() + "Z"
        return value.isoformat()

    return json.dumps(value, cls=EdxJSONEncoder)


def deserialize_field(field, value):
    """
    Deserialize the string version to the value stored internally.

    Note that this is not the same as the value returned by from_json, as model types typically store
    their value internally as JSON. By default, this method will return the result of calling json.loads
    on the supplied value, unless json.loads throws a TypeError, or the type of the value returned by json.loads
    is not supported for this class (from_json throws an Error). In either of those cases, this method returns
    the input value.
    """
    try:
        deserialized = json.loads(value)
        if deserialized is None:
            return deserialized
        try:
            field.from_json(deserialized)
            return deserialized
        except (ValueError, TypeError):
            # Support older serialized version, which was just a string, not result of json.dumps.
            # If the deserialized version cannot be converted to the type (via from_json),
            # just return the original value. For example, if a string value of '3.4' was
            # stored for a String field (before we started storing the result of json.dumps),
            # then it would be deserialized as 3.4, but 3.4 is not supported for a String
            # field. Therefore field.from_json(3.4) will throw an Error, and we should
            # actually return the original value of '3.4'.
            return value

    except (ValueError, TypeError):
        # Support older serialized version.
        return value


def own_metadata(block):
    """
    Return a JSON-friendly dictionary that contains only non-inherited field
    keys, mapped to their serialized values
    """
    return block.get_explicitly_set_fields_by_scope(Scope.settings)


@XBlock.needs("i18n")
# We 'want' the user service, but we don't strictly 'need' it.
# This makes our block more resilient. It won't crash in test environments
# where the user service might not be available.
@XBlock.wants("user")
class HtmlBlock(XBlock):
    """
    The HTML XBlock.
    """

    # Indicates that this XBlock has been extracted from edx-platform.
    is_extracted = True
    display_name = String(
        display_name=_("Display Name"),
        help=_("The display name for this component."),
        scope=Scope.settings,
        # it'd be nice to have a useful default but it screws up other things; so,
        # use display_name_with_default for those
        default=_("Text"),
    )
    data = String(help=_("Html contents to display for this block"), default="", scope=Scope.content)
    source_code = String(
        help=_("Source code for LaTeX documents. This feature is not well-supported."), scope=Scope.settings
    )
    use_latex_compiler = Boolean(help=_("Enable LaTeX templates?"), default=False, scope=Scope.settings)
    editor = String(
        help=_(
            "Select Visual to enter content and have the editor automatically create the HTML. Select Raw to edit "
            "HTML directly. If you change this setting, you must save the component and then re-open it for editing."
        ),
        display_name=_("Editor"),
        default="visual",
        values=[{"display_name": _("Visual"), "value": "visual"}, {"display_name": _("Raw"), "value": "raw"}],
        scope=Scope.settings,
    )

    ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA = "ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA"

    uses_xmodule_styles_setup = True
    filename_extension = "xml"
    template_dir_name = "html"
    show_in_read_only_mode = True

    xml_attributes = Dict(
        help="Map of unhandled xml attributes, used only for storage between import and export",
        default={},
        scope=Scope.settings,
    )
    metadata_to_strip = (
        "data_dir",
        "tabs",
        "grading_policy",
        "discussion_blackouts",
        # VS[compat]
        # These attributes should have been removed from here once all 2012-fall courses imported into
        # the CMS and "inline" OLX format deprecated. But, it never got deprecated. Moreover, it's
        # widely used to this date. So, we still have to strip them. Also, removing of "filename"
        # changes OLX returned by `/api/olx-export/v1/xblock/{block_id}/`, which indicates that some
        # places in the platform rely on it.
        "course",
        "org",
        "url_name",
        "filename",
        # Used for storing xml attributes between import and export, for roundtrips
        "xml_attributes",
        # Used by _import_xml_node_to_parent in cms/djangoapps/contentstore/helpers.py to prevent
        # XmlMixin from treating some XML nodes as "pointer nodes".
        "x-is-pointer-node",
    )

    # This is a categories to fields map that contains the block category specific fields which should not be
    # cleaned and/or override while adding xml to node.
    metadata_to_not_to_clean = {
        # A category `video` having `sub` and `transcripts` fields
        # which should not be cleaned/override in an xml object.
        "video": ("sub", "transcripts")
    }

    metadata_to_export_to_policy = ("discussion_topics",)

    @property
    def category(self):
        return self.scope_ids.block_type

    @property
    def location(self):
        return self.scope_ids.usage_id

    @location.setter
    def location(self, value):
        assert isinstance(value, UsageKey)
        self.scope_ids = self.scope_ids._replace(
            def_id=value,  # Note: assigning a UsageKey as def_id is OK in old mongo / import system but wrong in split
            usage_id=value,
        )

    @property
    def url_name(self):
        return self.location.block_id

    @property
    def xblock_kvs(self):
        """
        Retrieves the internal KeyValueStore for this XModule.

        Should only be used by the persistence layer. Use with caution.
        """
        # if caller wants kvs, caller's assuming it's up to date; so, decache it
        self.save()
        return self._field_data._kvs  # pylint: disable=protected-access

    @XBlock.supports("multi_device")
    def student_view(self, _context):
        """Return a fragment that contains the html for the student view."""
        frag = Fragment(self.get_html())
        frag.add_css(resource_loader.load_unicode("static/css/html.css"))
        frag.add_javascript("""function HtmlBlock(runtime, element){}""")
        frag.initialize_js("HtmlBlock")
        return frag

    @XBlock.supports("multi_device")
    def public_view(self, context):
        """Returns a fragment that contains the html for the preview view."""
        return self.student_view(context)

    def student_view_data(self, context=None):  # pylint: disable=unused-argument
        """Return a JSON representation of the student_view of this XBlock."""
        if getattr(settings, "FEATURES", {}).get(self.ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA, False):
            return {"enabled": True, "html": self.get_html()}
        else:
            return {
                "enabled": False,
                "message": f'To enable, set FEATURES["{self.ENABLE_HTML_XBLOCK_STUDENT_VIEW_DATA}"]',
            }

    def get_html(self):
        """Returns html required for rendering the block."""
        if not self.data:
            return self.data

        data = self.data

        # This code is now more defensive.
        # We check if the user service and the user object exist before using them.
        # This prevents crashes if they are not available.
        user_service = self.runtime.service(self, "user")
        if user_service:
            current_user = user_service.get_current_user()
            if current_user:
                user_id = current_user.opt_attrs.get(ATTR_KEY_DEPRECATED_ANONYMOUS_USER_ID)
                if user_id:
                    data = data.replace("%%USER_ID%%", user_id)

        # The course ID replacement is always safe to run.
        data = data.replace("%%COURSE_ID%%", str(self.scope_ids.usage_id.context_key))
        return data

    def studio_view(self, context=None):  # pylint: disable=unused-argument
        """Return a fragment that contains the html for the studio view."""
        frag = Fragment(self.get_html())
        frag.add_javascript("""function HtmlBlock(runtime, element){}""")
        frag.initialize_js("HtmlBlock")
        return frag

    # VS[compat] TODO (cpennington): Delete this method once all fall 2012 course
    # are being edited in the cms
    @classmethod
    def backcompat_paths(cls, filepath):
        """
        Get paths for html and xml files.
        """
        if filepath.endswith(".html.xml"):
            filepath = filepath[:-9] + ".html"  # backcompat--look for html instead of xml
        if filepath.endswith(".html.html"):
            filepath = filepath[:-5]  # some people like to include .html in filenames..
        candidates = []
        while os.sep in filepath:
            candidates.append(filepath)
            _, _, filepath = filepath.partition(os.sep)

        # also look for .html versions instead of .xml
        new_candidates = []
        for candidate in candidates:
            if candidate.endswith(".xml"):
                new_candidates.append(candidate[:-4] + ".html")
        return candidates + new_candidates

    @classmethod
    def filter_templates(cls, template, course):
        """
        Filter template that contains 'latex' from templates.

        Show them only if use_latex_compiler is set to True in
        course settings.
        """
        return "latex" not in template["template_id"] or course.use_latex_compiler

    def get_context(self):
        """
        an override to add in specific rendering context, in this case we need to
        add in a base path to our c4x content addressing scheme
        """
        # Add some specific HTML rendering context when editing HTML blocks where we pass
        # the root /c4x/ url for assets. This allows client-side substitutions to occur.
        return {
            "module": self,
            "editable_metadata_fields": self.editable_metadata_fields,  # pylint: disable=no-member
            "data": self.data,
            "base_asset_url": self.get_base_url_path_for_course_assets(self.location.course_key),
            "enable_latex_compiler": self.use_latex_compiler,
            "editor": self.editor,
        }

    def index_dictionary(self):
        xblock_body = super().index_dictionary()
        # Removing script and style
        html_content = re.sub(
            re.compile(
                r"""
                    <script>.*?</script> |
                    <style>.*?</style>
                """,
                re.DOTALL | re.VERBOSE,
            ),
            "",
            self.data,
        )
        html_content = escape_html_characters(html_content)
        html_body = {
            "html_content": html_content,
            "display_name": self.display_name,
        }
        if "content" in xblock_body:
            xblock_body["content"].update(html_body)
        else:
            xblock_body["content"] = html_body
        xblock_body["content_type"] = "Text"
        return xblock_body

    def bind_for_student(self, user_id, wrappers=None):
        """
        Set up this XBlock to act as an XModule instead of an XModuleDescriptor.

        Arguments:
            user_id: The user_id to set in scope_ids
            wrappers: These are a list functions that put a wrapper, such as
                      LmsFieldData or OverrideFieldData, around the field_data.
                      Note that the functions will be applied in the order in
                      which they're listed. So [f1, f2] -> f2(f1(field_data))
        """

        # Skip rebinding if we're already bound a user, and it's this user.
        if self.scope_ids.user_id is not None and user_id == self.scope_ids.user_id:
            if getattr(self.runtime, "position", None):
                # update the position of the tab
                self.position = self.runtime.position  # pylint: disable=attribute-defined-outside-init
            return

        # # If we are switching users mid-request, save the data from the old user.
        # self.save()

        # Update scope_ids to point to the new user.
        self.scope_ids = self.scope_ids._replace(user_id=user_id)

        # Clear out any cached instantiated children.
        self.clear_child_cache()

        # Clear out any cached field data scoped to the old user.
        for field in self.fields.values():
            if field.scope in (Scope.parent, Scope.children):
                continue

            if field.scope.user == UserScope.ONE:
                field._del_cached_value(self)  # pylint: disable=protected-access
                # not the most elegant way of doing this, but if we're removing
                # a field from the module's field_data_cache, we should also
                # remove it from its _dirty_fields
                if field in self._dirty_fields:
                    del self._dirty_fields[field]

        if wrappers:
            # Put user-specific wrappers around the field-data service for this block.
            # Note that these are different from modulestore.xblock_field_data_wrappers, which are not user-specific.
            wrapped_field_data = self.runtime.service(self, "field-data-unbound")
            for wrapper in wrappers:
                wrapped_field_data = wrapper(wrapped_field_data)
            self._bound_field_data = wrapped_field_data  # pylint: disable=attribute-defined-outside-init
            if getattr(self.runtime, "uses_deprecated_field_data", False):
                # This approach is deprecated but old mongo's CachingDescriptorSystem still requires it.
                # For Split mongo's CachingDescriptor system, don't set ._field_data this way.
                self._field_data = wrapped_field_data

    @staticmethod
    def serialize_asset_key_with_slash(asset_key):
        """
        Legacy code expects the serialized asset key to start w/ a slash; so, do that in one place
        :param asset_key:
        """
        url = str(asset_key)
        if not url.startswith("/"):
            url = "/" + url  # TODO - re-address this once LMS-11198 is tackled.
        return url

    @staticmethod
    def get_base_url_path_for_course_assets(course_key):  # pylint: disable=missing-function-docstring
        if (course_key is None) or isinstance(course_key, LibraryLocatorV2):
            return None

        assert isinstance(course_key, CourseKey)
        placeholder_id = uuid.uuid4().hex
        # create a dummy asset location with a fake but unique name. strip off the name, and return it
        url_path = HtmlBlock.serialize_asset_key_with_slash(
            course_key.make_asset_key("asset", placeholder_id).for_branch(None)
        )
        return url_path.replace(placeholder_id, "")

    def save(self):
        """Save block data."""
        if hasattr(self, "children"):
            self.children = [str(c) for c in self.children]
        super().save()

    @staticmethod
    def workbench_scenarios():
        """Create canned scenario for display in the workbench."""
        return [
            ("HtmlBlock", """<_html_extracted/>"""),
            (
                "Multiple HtmlBlock",
                """<vertical_demo><_html_extracted/><_html_extracted/><_html_extracted/></vertical_demo>""",
            ),
        ]

    @classmethod
    def clean_metadata_from_xml(cls, xml_object, excluded_fields=()):
        """
        Remove any attribute named for a field with scope Scope.settings from the supplied
        xml_object
        """
        for field_name, field in cls.fields.items():  # pylint: disable=no-member
            if (
                field.scope == Scope.settings
                and field_name not in excluded_fields
                and xml_object.get(field_name) is not None
            ):
                del xml_object.attrib[field_name]

    @classmethod
    def file_to_xml(cls, file_object):
        """
        Used when this module wants to parse a file object to xml
        that will be converted to the definition.

        Returns an lxml Element
        """
        return etree.parse(file_object, parser=EDX_XML_PARSER).getroot()  # CHANGEE

    @classmethod
    def load_file(cls, filepath, fs, def_id):
        """
        Open the specified file in fs, and call cls.file_to_xml on it,
        returning the lxml object.

        Add details and reraise on error.
        """
        try:
            with fs.open(filepath) as xml_file:
                return cls.file_to_xml(xml_file)
        except Exception as err:
            # Add info about where we are, but keep the traceback
            raise Exception(f"Unable to load file contents at path {filepath} for item {def_id}: {err}") from err

    # NOTE: html descriptors are special.  We do not want to parse and
    # export them ourselves, because that can break things (e.g. lxml
    # adds body tags when it exports, but they should just be html
    # snippets that will be included in the middle of pages.

    @classmethod
    def load_definition(cls, xml_object, system, location, id_generator):  # pylint: disable=unused-argument
        """Load a descriptor from the specified xml_object:

        If there is a filename attribute, load it as a string, and
        log a warning if it is not parseable by etree.HTMLParser.

        If there is not a filename attribute, the definition is the body
        of the xml_object, without the root tag (do not want <html> in the
        middle of a page)

        Args:
            xml_object: an lxml.etree._Element containing the definition to load
            system: the modulestore system or runtime which caches data
            location: the usage id for the block--used to compute the filename if none in the xml_object
            id_generator: used by other impls of this method to generate the usage_id
        """
        filename = xml_object.get("filename")
        if filename is None:
            definition_xml = copy.deepcopy(xml_object)
            cls.clean_metadata_from_xml(definition_xml)
            return {"data": stringify_children(definition_xml)}, []
        else:
            # html is special.  cls.filename_extension is 'xml', but
            # if 'filename' is in the definition, that means to load
            # from .html
            # 'filename' in html pointers is a relative path
            # (not same as 'html/blah.html' when the pointer is in a directory itself)
            pointer_path = "{category}/{url_path}".format(category="html", url_path=name_to_pathname(location.block_id))
            base = path(pointer_path).dirname()
            # log.debug("base = {0}, base.dirname={1}, filename={2}".format(base, base.dirname(), filename))
            filepath = f"{base}/{filename}.html"
            # log.debug("looking for html file for {0} at {1}".format(location, filepath))

            # VS[compat]
            # TODO (cpennington): If the file doesn't exist at the right path,
            # give the class a chance to fix it up. The file will be written out
            # again in the correct format.  This should go away once the CMS is
            # online and has imported all current (fall 2012) courses from xml
            if not system.resources_fs.exists(filepath):

                candidates = cls.backcompat_paths(filepath)
                # log.debug("candidates = {0}".format(candidates))
                for candidate in candidates:
                    if system.resources_fs.exists(candidate):
                        filepath = candidate
                        break
            try:
                with system.resources_fs.open(filepath, encoding="utf-8") as infile:
                    html = infile.read()
                    # Log a warning if we can't parse the file, but don't error
                    if len(html) > 0 and not check_html(html):
                        msg = f"Couldn't parse html in {filepath}"
                        log.warning(msg)
                        system.error_tracker("Warning: " + msg)

                    definition = {"data": html}

                    # TODO (ichuang): remove this after migration
                    # for Fall 2012 LMS migration: keep filename (and unmangled filename)
                    definition["filename"] = [filepath, filename]

                    return definition, []

            except ResourceNotFound as err:
                msg = "Unable to load file contents at path {}: {} ".format(filepath, err)
                # add more info and re-raise
                raise Exception(msg).with_traceback(sys.exc_info()[2])

    @classmethod
    def load_metadata(cls, xml_object):
        """
        Read the metadata attributes from this xml_object.

        Returns a dictionary {key: value}.
        """
        metadata = {"xml_attributes": {}}
        for attr, val in xml_object.attrib.items():

            if attr in cls.metadata_to_strip:
                # don't load these
                continue

            if attr not in cls.fields:  # pylint: disable=unsupported-membership-test
                metadata["xml_attributes"][attr] = val
            else:
                metadata[attr] = deserialize_field(cls.fields[attr], val)  # pylint: disable=unsubscriptable-object
        return metadata

    @classmethod
    def apply_policy(cls, metadata, policy):
        """
        Add the keys in policy to metadata, after processing them
        through the attrmap.  Updates the metadata dict in place.
        """
        for attr, value in policy.items():
            if attr not in cls.fields:  # pylint: disable=unsupported-membership-test
                # Store unknown attributes coming from policy.json
                # in such a way that they will export to xml unchanged
                metadata["xml_attributes"][attr] = value
            else:
                metadata[attr] = value

    @classmethod
    def parse_xml(cls, node, runtime, keys):
        """
        Use `node` to construct a new block.

        Arguments:
            node (etree.Element): The xml node to parse into an xblock.

            runtime (:class:`.Runtime`): The runtime to use while parsing.

            keys (:class:`.ScopeIds`): The keys identifying where this block
                will store its data.

        Returns (XBlock): The newly parsed XBlock

        """

        if keys is None:
            # Passing keys=None is against the XBlock API but some platform tests do it.
            def_id = runtime.id_generator.create_definition(node.tag, node.get("url_name"))
            keys = ScopeIds(None, node.tag, def_id, runtime.id_generator.create_usage(def_id))
        aside_children = []

        # Let the runtime construct the block. It will have a proper, inheritance-aware field data store.
        block = runtime.construct_xblock_from_class(cls, keys)

        # VS[compat]
        # In 2012, when the platform didn't have CMS, and all courses were handwritten XML files, problem tags
        # contained XML problem descriptions withing themselves. Later, when Studio has been created, and "pointer" tags
        # became the preferred problem format, edX has to add this compatibility code to 1) support both pre- and
        # post-Studio course formats simulteneously, and 2) be able to migrate 2012-fall courses to Studio. Old style
        # support supposed to be removed, but the deprecation process have never been initiated, so this
        # compatibility must stay, probably forever.
        if is_pointer_tag(node):
            # new style:
            # read the actual definition file--named using url_name.replace(':','/')
            definition_xml, filepath = cls.load_definition_xml(node, runtime, keys.def_id)
            aside_children = runtime.parse_asides(definition_xml, keys.def_id, keys.usage_id, runtime.id_generator)
        else:
            filepath = None
            definition_xml = node

        # Note: removes metadata.
        definition, children = cls.load_definition(definition_xml, runtime, keys.def_id, runtime.id_generator)

        # VS[compat]
        # Make Ike's github preview links work in both old and new file layouts.
        if is_pointer_tag(node):
            # new style -- contents actually at filepath
            definition["filename"] = [filepath, filepath]

        metadata = cls.load_metadata(definition_xml)

        # move definition metadata into dict
        dmdata = definition.get("definition_metadata", "")
        if dmdata:
            metadata["definition_metadata_raw"] = dmdata
            try:
                metadata.update(json.loads(dmdata))
            except Exception as err:  # lint-amnesty, pylint: disable=broad-except
                log.debug("Error in loading metadata %r", dmdata, exc_info=True)
                metadata["definition_metadata_err"] = str(err)

        definition_aside_children = definition.pop("aside_children", None)
        if definition_aside_children:
            aside_children.extend(definition_aside_children)

        # Set/override any metadata specified by policy
        cls.apply_policy(metadata, runtime.get_policy(keys.usage_id))

        field_data = {**metadata, **definition}

        for field_name, value in field_data.items():
            # The 'xml_attributes' field has a special setter logic in its Field class,
            # so we must handle it carefully to avoid duplicating data.
            if field_name == "xml_attributes":
                # The 'filename' attribute is specially handled for git links.
                value["filename"] = definition.get("filename", ["", None])
                block.xml_attributes.update(value)
            elif field_name in block.fields:
                setattr(block, field_name, value)

        block.children = children

        if aside_children:
            cls.add_applicable_asides_to_block(block, runtime, aside_children)

        return block

    @classmethod
    def add_applicable_asides_to_block(cls, block, runtime, aside_children):
        """
        Add asides to the block. Moved this out of the parse_xml method to use it in the VideoBlock.parse_xml
        """
        asides_tags = [aside_child.tag for aside_child in aside_children]
        asides = runtime.get_asides(block)
        for aside in asides:
            if aside.scope_ids.block_type in asides_tags:
                block.add_aside(aside)

    @classmethod
    def parse_xml_new_runtime(cls, node, runtime, keys):
        """
        Parse XML in the new learning-core-based runtime. Since it doesn't yet
        support loading separate .html files, the HTML data is assumed to be in
        a CDATA child or otherwise just inline in the OLX.
        """
        block = runtime.construct_xblock_from_class(cls, keys)
        block.data = stringify_children(node)
        # Attributes become fields.
        for name, value in node.items():
            cls._set_field_if_present(block, name, value, {})
        return block

    @classmethod
    def load_definition_xml(cls, node, runtime, def_id):
        """
        Loads definition_xml stored in a dedicated file
        """
        url_name = node.get("url_name")
        filepath = cls._format_filepath(node.tag, name_to_pathname(url_name))
        definition_xml = cls.load_file(filepath, runtime.resources_fs, def_id)
        return definition_xml, filepath

    @classmethod
    def _format_filepath(cls, category, name):
        """Formats a path to an XML definition file."""
        return f"{category}/{name}.{cls.filename_extension}"

    def export_to_file(self):
        """If this returns True, write the definition of this block to a separate
        file.

        NOTE: Do not override this without a good reason.  It is here
        specifically for customtag...
        """
        return True

    def add_xml_to_node(self, node):
        """For exporting, set data on `node` from ourselves."""
        xml_object = self.definition_to_xml(self.runtime.export_fs)
        if xml_object is None:
            return

        for aside in self.runtime.get_asides(self):
            if aside.needs_serialization():
                aside_node = etree.Element("unknown_root", nsmap=XML_NAMESPACES)
                aside.add_xml_to_node(aside_node)
                xml_object.append(aside_node)

        not_to_clean_fields = self.metadata_to_not_to_clean.get(self.category, ())
        self.clean_metadata_from_xml(xml_object, excluded_fields=not_to_clean_fields)
        xml_object.tag = self.category
        node.tag = self.category

        for attr in sorted(own_metadata(self)):
            if (
                attr not in self.metadata_to_strip
                and attr not in self.metadata_to_export_to_policy
                and attr not in not_to_clean_fields
            ):
                # pylint: disable=unsubscriptable-object
                val = serialize_field(self.fields[attr].to_json(getattr(self, attr)))
                try:
                    xml_object.set(attr, val)
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.exception("Failed to serialize metadata attribute %s in module %s.", attr, self.url_name)

        for key, value in self.xml_attributes.items():
            if key not in self.metadata_to_strip:
                xml_object.set(key, serialize_field(value))

        if self.export_to_file():
            url_path = name_to_pathname(self.url_name)
            filepath = self._format_filepath(
                self.category, self.location.run if self.category == "course" else url_path
            )
            self.runtime.export_fs.makedirs(os.path.dirname(filepath), recreate=True)
            with self.runtime.export_fs.open(filepath, "wb") as fileobj:
                ElementTree(xml_object).write(fileobj, pretty_print=True, encoding="utf-8")
        else:
            node.clear()
            node.tag = xml_object.tag
            node.text = xml_object.text
            node.tail = xml_object.tail
            node.attrib.update(xml_object.attrib)
            node.extend(xml_object)

        if not node.get("url_name"):
            node.set("url_name", self.url_name)

        if self.category == "course":
            node.set("org", self.location.org)
            node.set("course", self.location.course)

    def definition_to_xml(self, resource_fs):
        """
        Returns an lxml Element representing the definition of this block.
        This version creates a self-contained definition file that includes
        all necessary metadata for a successful re-import.
        """

        # Write html to file, return an empty tag
        pathname = name_to_pathname(self.url_name)
        filepath = "{category}/{pathname}.html".format(category=self.category, pathname=pathname)

        resource_fs.makedirs(os.path.dirname(filepath), recreate=True)
        with resource_fs.open(filepath, "wb") as filestream:
            html_data = self.data.encode("utf-8")
            filestream.write(html_data)

        # write out the relative name
        relname = path(pathname).basename()

        elt = etree.Element("html")
        elt.set("filename", relname)
        return elt

    @property
    def non_editable_metadata_fields(self):
        """`use_latex_compiler` should not be editable in the Studio settings editor."""
        # pylint: disable=no-member
        return super().non_editable_metadata_fields + [HtmlBlock.xml_attributes, HtmlBlock.use_latex_compiler]
