import copy
import json
import logging

from lxml import etree
from lxml.etree import ElementTree, XMLParser
from xblock.fields import Scope
from xblock.runtime import KeyValueStore, KvsFieldData


log = logging.getLogger(__name__)

EDX_XML_PARSER = XMLParser(
    dtd_validation=False, load_dtd=False, remove_blank_text=True, encoding="utf-8"
)


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


class InheritanceKeyValueStore(KeyValueStore):
    """
    Common superclass for kvs's which know about inheritance of settings. Offers simple
    dict-based storage of fields and lookup of inherited values.

    Note: inherited_settings is a dict of key to json values (internal xblock field repr)

    Using this KVS is an alternative to using InheritingFieldData(). That one works with any KVS, like
    DictKeyValueStore, and doesn't require any special behavior. On the other hand, this InheritanceKeyValueStore only
    does inheritance properly if you first use compute_inherited_metadata() to walk the tree of XBlocks and pre-compute
    the inherited metadata for the whole tree, storing it in the inherited_settings field of each instance of this KVS.

    🟥 Warning: Unlike the base class, this KVS makes the assumption that you're using a completely separate KVS
       instance for every XBlock, so that we only have to look at the "field_name" part of the key. You cannot use this
       as a drop-in replacement for DictKeyValueStore for this reason.
    """

    def __init__(self, initial_values=None, inherited_settings=None):
        super().__init__()
        self.inherited_settings = inherited_settings or {}
        self._fields = initial_values or {}

    def get(self, key):
        return self._fields[key.field_name]

    def set(self, key, value):
        # xml backed courses are read-only, but they do have some computed fields
        self._fields[key.field_name] = value

    def delete(self, key):
        del self._fields[key.field_name]

    def has(self, key):
        return key.field_name in self._fields

    def default(self, key):
        """
        Check to see if the default should be from inheritance. If not
        inheriting, this will raise KeyError which will cause the caller to use
        the field's global default.
        """
        return self.inherited_settings[key.field_name]


class XmlMixin:
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
    def clean_metadata_from_xml(cls, xml_object, excluded_fields=()):
        """
        Remove any attribute named for a field with scope Scope.settings from the supplied
        xml_object
        """
        for field_name, field in cls.fields.items():
            if (
                field.scope == Scope.settings
                and field_name not in excluded_fields
                and xml_object.get(field_name) is not None
            ):
                del xml_object.attrib[field_name]

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
        return f"{category}/{name}.xml"

    @classmethod
    def file_to_xml(cls, file_object):
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
        except Exception as err:  # lint-amnesty, pylint: disable=broad-except
            # Add info about where we are, but keep the traceback
            raise Exception(
                f"Unable to load file contents at path {filepath} for item {def_id}: {err}"
            ) from err

    @classmethod
    def definition_from_xml(
        cls, xml_object, system
    ):  # lint-amnesty, pylint: disable=unused-argument
        if len(xml_object) == 0 and len(list(xml_object.items())) == 0:
            return {"data": ""}, []
        return {
            "data": etree.tostring(xml_object, pretty_print=True, encoding="unicode")
        }, []

    @classmethod
    def load_definition(cls, xml_object, system, def_id, id_generator):
        """
        Load a block from the specified xml_object.
        Subclasses should not need to override this except in special
        cases (e.g. html block)

        Args:
            xml_object: an lxml.etree._Element containing the definition to load
            system: the modulestore system (aka, runtime) which accesses data and provides access to services
            def_id: the definition id for the block--used to compute the usage id and asides ids
            id_generator: used to generate the usage_id
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

            # VS[compat]
            # If the file doesn't exist at the right path, give the class a chance to fix it up. The file will be
            # written out again in the correct format. This should have gone away once the CMS became online and had
            # imported all 2012-fall courses from XML.
            if not system.resources_fs.exists(filepath) and hasattr(
                cls, "backcompat_paths"
            ):
                candidates = cls.backcompat_paths(filepath)
                for candidate in candidates:
                    if system.resources_fs.exists(candidate):
                        filepath = candidate
                        break

            definition_xml = cls.load_file(filepath, system.resources_fs, def_id)
            usage_id = id_generator.create_usage(def_id)
            aside_children = system.parse_asides(
                definition_xml, def_id, usage_id, id_generator
            )

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

            if attr not in cls.fields:
                metadata["xml_attributes"][attr] = val
            else:
                metadata[attr] = deserialize_field(cls.fields[attr], val)
        return metadata

    @classmethod
    def apply_policy(cls, metadata, policy):
        """
        Add the keys in policy to metadata, after processing them
        through the attrmap.  Updates the metadata dict in place.
        """
        for attr, value in policy.items():
            if attr not in cls.fields:
                # Store unknown attributes coming from policy.json
                # in such a way that they will export to xml unchanged
                metadata["xml_attributes"][attr] = value
            else:
                metadata[attr] = value
