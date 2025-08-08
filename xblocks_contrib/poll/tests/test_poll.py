"""
Tests for PollBlock
"""

import json

from django.test import TestCase
from lxml import etree
from opaque_keys.edx.keys import CourseKey
from xblock.field_data import DictFieldData
from xblock.fields import ScopeIds
from xblock.test.tools import TestRuntime

from xblocks_contrib import PollBlock


class PollBlockTest(TestCase):
    """Logic tests for Poll Xmodule."""

    raw_field_data = {"poll_answers": {"Yes": 1, "Dont_know": 0, "No": 0}, "voted": False, "poll_answer": "Yes"}

    def setUp(self):
        super().setUp()
        course_key = CourseKey.from_string("org/course/run")
        self.system = TestRuntime()

        # ScopeIds: (user_id, block_type, def_id, usage_id)
        usage_key = course_key.make_usage_key("block_type", "test_loc")
        self.scope_ids = ScopeIds(1, "block_type", usage_key, usage_key)
        self.xblock = PollBlock(self.system, DictFieldData(self.raw_field_data), self.scope_ids)

    def test_poll_block_construction(self):
        """Test to ensure that the PollBlock is constructed properly and data is imported"""

        # Check if the xblock object is an instance of PollBlock
        self.assertIsInstance(self.xblock, PollBlock)

        # Verify that the imported data is correctly assigned to the PollBlock's fields
        self.assertEqual(self.xblock.poll_answers, {"Yes": 1, "Dont_know": 0, "No": 0})
        self.assertEqual(self.xblock.voted, False)
        self.assertEqual(self.xblock.poll_answer, "Yes")

        # Verify the scope_ids to ensure the PollBlock is using the correct context
        self.assertEqual(self.xblock.scope_ids.user_id, 1)
        self.assertEqual(self.xblock.scope_ids.block_type, "block_type")

        # You can also verify some other behavior if necessary
        # For example, check that the `poll_answers` field is being correctly updated.
        self.xblock.poll_answers["Maybe"] = 1
        self.assertEqual(self.xblock.poll_answers["Maybe"], 1)

    def test_vote_success(self):
        response = self.xblock.submit_answer("No")
        assert response["poll_answers"]["No"] == 1
        assert response["total"] == 2
        assert self.xblock.voted is True
        assert self.xblock.poll_answer == "No"
