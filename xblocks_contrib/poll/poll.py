"""Poll block is ungraded xmodule used by students to
to do set of polls.

On the client side we show:
If student does not yet anwered - Question with set of choices.
If student have answered - Question with statistics for each answers.
"""

import copy
import datetime
import json
import logging
from collections import OrderedDict
from copy import deepcopy

import markupsafe
from django.utils.translation import gettext_noop as _
from lxml import etree
from opaque_keys.edx.keys import UsageKey
from web_fragments.fragment import Fragment
from xblock.core import XML_NAMESPACES, XBlock
from xblock.fields import Boolean, Dict, List, Scope, ScopeIds, String
from xblock.utils.resources import ResourceLoader

Text = markupsafe.escape
resource_loader = ResourceLoader(__name__)
log = logging.getLogger(__name__)

# assume all XML files are persisted as utf-8.
EDX_XML_PARSER = etree.XMLParser(dtd_validation=False, load_dtd=False, remove_blank_text=True, encoding="utf-8")


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

    return json.dumps(value)


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


def HTML(html):  # pylint: disable=invalid-name
    """
    Mark a string as already HTML, so that it won't be escaped before output.

    Use this function when formatting HTML into other strings.  It must be
    used in conjunction with ``Text()``, and both ``HTML()`` and ``Text()``
    must be closed before any calls to ``format()``::

        <%page expression_filter="h"/>
        <%!
        from django.utils.translation import gettext as _

        from openedx.core.djangolib.markup import HTML, Text
        %>
        ${Text(_("Write & send {start}email{end}")).format(
            start=HTML("<a href='mailto:{}'>").format(user.email),
            end=HTML("</a>"),
        )}

    """
    return markupsafe.Markup(html)


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


@XBlock.needs("i18n")
class PollBlock(XBlock):
    """Poll Block"""

    # Indicates that this XBlock has been extracted from edx-platform.
    is_extracted = True

    # Name of poll to use in links to this poll
    display_name = String(
        help=_("The display name for this component."),
        scope=Scope.settings,
        default="poll_question",
    )

    voted = Boolean(help=_("Whether this student has voted on the poll"), scope=Scope.user_state, default=False)
    poll_answer = String(help=_("Student answer"), scope=Scope.user_state, default="")
    poll_answers = Dict(help=_("Poll answers from all students"), scope=Scope.user_state_summary)

    # List of answers, in the form {'id': 'some id', 'text': 'the answer text'}
    answers = List(help=_("Poll answers from xml"), scope=Scope.content, default=[])

    question = String(help=_("Poll question"), scope=Scope.content, default="")

    # This is a categories to fields map that contains the block category specific fields which should not be
    # cleaned and/or override while adding xml to node.
    metadata_to_not_to_clean = {
        # A category `video` having `sub` and `transcripts` fields
        # which should not be cleaned/override in an xml object.
        "video": ("sub", "transcripts")
    }
    metadata_to_export_to_policy = ("discussion_topics",)
    js_module_name = "poll"

    # Extension to append to filename paths
    filename_extension = "xml"

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

    _tag_name = "poll_question"
    _child_tag_name = "answer"

    @property
    def xblock_kvs(self):
        """
        Retrieves the internal KeyValueStore for this XModule.

        Should only be used by the persistence layer. Use with caution.
        """
        # if caller wants kvs, caller's assuming it's up to date; so, decache it
        self.save()
        return self._field_data._kvs  # pylint: disable=protected-access

    @property
    def url_name(self):
        return self.location.block_id

    @property
    def course_id(self):
        return self.location.course_key

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

    def handle_ajax(self, dispatch, data):  # legacy support for tests
        """
        Legacy method to mimic old ajax handler behavior for backward compatibility.
        """
        if dispatch == "get_state":
            return json.dumps(self.handle_get_state(data))
        else:
            return json.dumps(self.submit_answer(dispatch))

    def student_view(self, _context):
        """
        Renders the student view.
        """

        frag = Fragment()
        frag.add_content(
            resource_loader.render_django_template(
                "templates/poll.html",
                {
                    "element_id": self.scope_ids.usage_id.html_id(),
                    "element_class": self.scope_ids.usage_id.block_type,
                    "configuration_json": self.dump_poll(),
                },
                i18n_service=self.runtime.service(self, "i18n"),
            )
        )
        frag.add_css(resource_loader.load_unicode("static/css/poll.css"))
        frag.add_javascript(resource_loader.load_unicode("static/js/src/poll.js"))
        frag.initialize_js("PollBlock")
        return frag

    def dump_poll(self):
        """Dump poll information.

        Returns:
            string - Serialize json.
        """
        # FIXME: hack for resolving caching `default={}` during definition
        # poll_answers field

        if self.poll_answers is None:
            self.poll_answers = {}

        answers_to_json = OrderedDict()

        # # # FIXME: fix this, when xblock support mutable types.
        # # # Now we use this hack.
        temp_poll_answers = self.poll_answers

        # # # Fill self.poll_answers, prepare data for template context.
        for answer in self.answers:
            # Set default count for answer = 0.
            if answer["id"] not in temp_poll_answers:
                temp_poll_answers[answer["id"]] = 0
            answers_to_json[answer["id"]] = answer["text"]
        self.poll_answers = temp_poll_answers

        return json.dumps(
            {
                "answers": answers_to_json,
                "question": self.question,
                "poll_answer": self.poll_answer,
                "poll_answers": self.poll_answers,
                "total": sum(self.poll_answers.values()) if self.voted else 0,
                "reset": str(self.xml_attributes.get("reset", "true")).lower(),
            }
        )

    @XBlock.json_handler
    def handle_get_state(self, data, suffix=""):  # pylint: disable=unused-argument
        return {
            "poll_answer": self.poll_answer,
            "poll_answers": self.poll_answers,
            "total": sum(self.poll_answers.values()),
        }

    def submit_answer(self, answer):
        """
        Submits a poll answer.
        """
        if not answer:
            return {"error": "No answer provided!"}

        if answer in self.poll_answers and not self.voted:
            # FIXME: fix this, when xblock will support mutable types.
            # Now we use this hack.
            temp_poll_answers = self.poll_answers
            temp_poll_answers[answer] += 1
            self.poll_answers = temp_poll_answers

            self.voted = True
            self.poll_answer = answer
            return {
                "poll_answers": self.poll_answers,
                "total": sum(self.poll_answers.values()),
                "callback": {"objectName": "Conditional"},
            }
        return {"error": "Unknown Command!"}

    @XBlock.json_handler
    def handle_submit_state(self, data, suffix=""):  # pylint: disable=unused-argument
        """
        handler to submit poll answer.
        """
        answer = data.get("answer")  # Extract the answer from the data payload
        return self.submit_answer(answer)

    @XBlock.json_handler
    def handle_reset_state(self):
        """
        handler to Reset poll answer.
        """

        self.voted = False

        # FIXME: fix this, when xblock will support mutable types.
        # Now we use this hack.
        temp_poll_answers = self.poll_answers
        temp_poll_answers[self.poll_answer] -= 1
        self.poll_answers = temp_poll_answers
        self.poll_answer = ""
        return {"status": "success"}

    @staticmethod
    def workbench_scenarios():
        """Create canned scenario for display in the workbench."""
        return [
            (
                "PollBlock",
                """<_poll_question_extracted/>
                """,
            ),
            (
                "Multiple PollBlock",
                """<vertical_demo>
                <_poll_question_extracted/>
                <_poll_question_extracted/>
                <_poll_question_extracted/>
                </vertical_demo>
                """,
            ),
        ]

    def get_explicitly_set_fields_by_scope(self, scope=Scope.content):
        """
        Get a dictionary of the fields for the given scope which are set explicitly on this xblock. (Including
        any set to None.)
        """
        result = {}
        for field in self.fields.values():
            if field.scope == scope and field.is_set_on(self):
                try:
                    result[field.name] = field.read_json(self)
                except TypeError as exception:
                    exception_message = "{message}, Block-location:{location}, Field-name:{field_name}".format(
                        message=str(exception), location=str(self.location), field_name=field.name
                    )
                    raise TypeError(exception_message)  # pylint: disable=raise-missing-from
        return result

    @staticmethod
    def _get_metadata_from_xml(xml_object, remove=True):
        """
        Extract the metadata from the XML.
        """
        meta = xml_object.find("meta")
        if meta is None:
            return ""
        dmdata = meta.text
        if remove:
            xml_object.remove(meta)
        return dmdata

    @classmethod
    def definition_from_xml(cls, xml_object, system):  # pylint: disable=unused-argument
        """
        Pull out the data into dictionary.
        """
        # Check for presense of required tags in xml.
        if len(xml_object.xpath(cls._child_tag_name)) == 0:
            raise ValueError(
                "Poll_question definition must include \
                at least one 'answer' tag"
            )

        xml_object_copy = deepcopy(xml_object)
        answers = []
        for element_answer in xml_object_copy.findall(cls._child_tag_name):
            answer_id = element_answer.get("id", None)
            if answer_id:
                answers.append({"id": answer_id, "text": stringify_children(element_answer)})
            xml_object_copy.remove(element_answer)

        definition = {"answers": answers, "question": stringify_children(xml_object_copy)}
        children = []
        return (definition, children)

    @classmethod
    def clean_metadata_from_xml(cls, xml_object, excluded_fields=()):
        """
        Remove any attribute named for a field with scope Scope.settings from the supplied
        xml_object
        """

        for field_name, field in getattr(cls, "fields", {}).items():  # pylint: disable=no-member
            if (
                field.scope == Scope.settings
                and field_name not in excluded_fields
                and xml_object.get(field_name) is not None
            ):
                del xml_object.attrib[field_name]

    @staticmethod
    def file_to_xml(file_object):
        """
        Used when this module wants to parse a file object to xml
        that will be converted to the definition.

        Returns an lxml Element
        """
        return etree.parse(file_object, parser=EDX_XML_PARSER).getroot()

    @classmethod
    def load_file(cls, filepath, fs, def_id):  # pylint: disable=invalid-name
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

    @classmethod
    def load_definition(cls, xml_object, system, def_id, id_generator):
        """
        Load a block from the specified xml_object.
        """

        # VS[compat]
        # The filename attr should have been removed once all 2012-fall courses imported into the CMS and "inline" OLX
        # format deprecated. This never happened, and `filename` is still used, so we have too keep both formats.
        filename = xml_object.get("filename")
        if filename is None:
            definition_xml = copy.deepcopy(xml_object)
            filepath = ""
            aside_children = []
        else:
            filepath = cls._format_filepath(xml_object.tag, filename)

            definition_xml = cls.load_file(filepath, system.resources_fs, def_id)
            usage_id = id_generator.create_usage(def_id)
            aside_children = system.parse_asides(definition_xml, def_id, usage_id, id_generator)

            # Add the attributes from the pointer node
            definition_xml.attrib.update(xml_object.attrib)

        definition_metadata = cls._get_metadata_from_xml(definition_xml)
        cls.clean_metadata_from_xml(definition_xml)
        definition, children = cls.definition_from_xml(definition_xml, system)
        if definition_metadata:
            definition["definition_metadata"] = definition_metadata
        definition["filename"] = [filepath, filename]

        if aside_children:
            definition["aside_children"] = aside_children

        return definition, children

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

            if attr not in getattr(cls, "fields", {}):  # pylint: disable=unsupported-membership-test
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
        Returns (XBlock): The newly parsed XBlock
        """

        if keys is None:
            def_id = runtime.id_generator.create_definition(node.tag, node.get("url_name"))
            keys = ScopeIds(None, node.tag, def_id, runtime.id_generator.create_usage(def_id))

        aside_children = []

        if is_pointer_tag(node):
            definition_xml, filepath = cls.load_definition_xml(node, runtime, keys.def_id)
            aside_children = runtime.parse_asides(definition_xml, keys.def_id, keys.usage_id, runtime.id_generator)
        else:
            filepath = None
            definition_xml = node

        definition, children = cls.load_definition(definition_xml, runtime, keys.def_id, runtime.id_generator)

        if is_pointer_tag(node):
            definition["filename"] = [filepath, filepath]

        metadata = cls.load_metadata(definition_xml)

        dmdata = definition.get("definition_metadata", "")
        if dmdata:
            metadata["definition_metadata_raw"] = dmdata
            try:
                metadata.update(json.loads(dmdata))
            except Exception as err:  # pylint: disable=broad-exception-caught
                log.debug("Error in loading metadata %r", dmdata, exc_info=True)
                metadata["definition_metadata_err"] = str(err)

        definition_aside_children = definition.pop("aside_children", None)
        if definition_aside_children:
            aside_children.extend(definition_aside_children)

        field_data = {**metadata, **definition, "children": children}
        field_data["xml_attributes"]["filename"] = definition.get("filename", ["", None])

        if "filename" in field_data:
            del field_data["filename"]

        # The "normal" / new way to set field data:
        xblock = runtime.construct_xblock_from_class(cls, keys)
        for key, value_jsonish in field_data.items():
            if key in cls.fields:  # pylint: disable=unsupported-membership-test
                setattr(xblock, key, cls.fields[key].from_json(value_jsonish))  # pylint: disable=unsubscriptable-object
            elif key == "children":
                xblock.children = value_jsonish
            else:
                log.warning(
                    "Imported %s XBlock does not have field %s found in XML.",
                    xblock.scope_ids.block_type,
                    key,
                )

        if aside_children:
            asides_tags = [x.tag for x in aside_children]
            asides = runtime.get_asides(xblock)
            for asd in asides:
                if asd.scope_ids.block_type in asides_tags:
                    xblock.add_aside(asd)
        return xblock

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
        return f"{category}/{name}.{cls.filename_extension}"

    def add_xml_to_node(self, node):
        """
        For exporting, set data on `node` from ourselves.
        """
        xml_object = self.definition_to_xml()

        # If xml_object is None, we don't know how to serialize this node, but
        # we shouldn't crash out the whole export for it.
        if xml_object is None:
            return

        for aside in self.runtime.get_asides(self):
            if aside.needs_serialization():
                aside_node = etree.Element("unknown_root", nsmap=XML_NAMESPACES)
                aside.add_xml_to_node(aside_node)
                xml_object.append(aside_node)

        not_to_clean_fields = self.metadata_to_not_to_clean.get(self.category, ())
        self.clean_metadata_from_xml(xml_object, excluded_fields=not_to_clean_fields)

        # Set the tag on both nodes so we get the file path right.
        xml_object.tag = self.category
        node.tag = self.category

        # Add the non-inherited metadata

        for attr in sorted(self.get_explicitly_set_fields_by_scope(Scope.settings)):
            # don't want e.g. data_dir
            if (
                attr not in self.metadata_to_strip
                and attr not in self.metadata_to_export_to_policy
                and attr not in not_to_clean_fields
            ):
                # pylint: disable=unsubscriptable-object
                val = serialize_field(self.fields[attr].to_json(getattr(self, attr)))
                try:
                    xml_object.set(attr, val)
                except Exception:  # pylint: disable=broad-except
                    logging.exception(
                        (
                            "Failed to serialize metadata attribute %s with value %s in module %s. "
                            "This could mean data loss!!!"
                        ),
                        attr,
                        val,
                        self.url_name,
                    )

        for key, value in self.xml_attributes.items():
            if key not in self.metadata_to_strip:
                xml_object.set(key, serialize_field(value))

        node.clear()
        node.tag = xml_object.tag
        node.text = xml_object.text
        node.tail = xml_object.tail
        node.attrib.update(xml_object.attrib)
        node.extend(xml_object)

        # Do not override an existing value for the course.
        if not node.get("url_name"):
            node.set("url_name", self.url_name)

        # Special case for course pointers:
        if self.category == "course":
            # add org and course attributes on the pointer tag
            node.set("org", self.location.org)
            node.set("course", self.location.course)

    def definition_to_xml(self, resource_fs=None):  # pylint: disable=unused-argument
        """Return an xml element representing to this definition."""

        poll_str = HTML("<{tag_name}>{text}</{tag_name}>").format(tag_name=self._tag_name, text=self.question)
        xml_object = etree.fromstring(poll_str)
        xml_object.set("display_name", self.display_name)

        def add_child(xml_obj, answer):  # pylint: disable=unused-argument
            # Escape answer text before adding to xml tree.
            answer_text = str(answer["text"])
            child_str = Text("{tag_begin}{text}{tag_end}").format(
                tag_begin=HTML('<{tag_name} id="{id}">').format(tag_name=self._child_tag_name, id=answer["id"]),
                text=answer_text,
                tag_end=HTML("</{tag_name}>").format(tag_name=self._child_tag_name),
            )
            child_node = etree.fromstring(child_str)
            xml_object.append(child_node)

        for answer in self.answers:
            add_child(xml_object, answer)

        return xml_object
