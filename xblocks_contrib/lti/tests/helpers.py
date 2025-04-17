"""
Utility methods for unit tests.
"""

import datetime
import re
from unittest.mock import Mock

from xblock.fields import JSONField
from xblock.reference.user_service import UserService, XBlockUser
from xblock.runtime import Runtime

TIMEDELTA_REGEX = re.compile(
    r'^'
    r'((?P<days>\d+?) day(?:s?))?(\s)?'
    r'((?P<hours>\d+?) hour(?:s?))?(\s)?'
    r'((?P<minutes>\d+?) minute(?:s)?)?(\s)?'
    r'((?P<seconds>\d+?) second(?:s)?)?'
    r'$'
)


class Timedelta(JSONField):  # lint-amnesty, pylint: disable=missing-class-docstring
    # Timedeltas are immutable, see http://docs.python.org/2/library/datetime.html#available-types
    MUTABLE = False

    def from_json(self, time_str):  # lint-amnesty, pylint: disable=arguments-renamed, inconsistent-return-statements
        """
        time_str: A string with the following components:
            <D> day[s] (optional)
            <H> hour[s] (optional)
            <M> minute[s] (optional)
            <S> second[s] (optional)

        Returns a datetime.timedelta parsed from the string
        """
        if time_str is None:
            return None

        if isinstance(time_str, datetime.timedelta):
            return time_str

        parts = TIMEDELTA_REGEX.match(time_str)
        if not parts:
            return
        parts = parts.groupdict()
        time_params = {}
        for (name, param) in parts.items():
            if param:
                time_params[name] = int(param)
        return datetime.timedelta(**time_params)

    def to_json(self, value):
        if value is None:
            return None

        values = []
        for attr in ('days', 'hours', 'minutes', 'seconds'):
            cur_value = getattr(value, attr, 0)
            if cur_value > 0:
                values.append("%d %s" % (cur_value, attr))
        return ' '.join(values)

    def enforce_type(self, value):
        """
        Ensure that when set explicitly the Field is set to a timedelta
        """
        if isinstance(value, datetime.timedelta) or value is None:
            return value

        return self.from_json(value)


class StubUserService(UserService):
    """
    Stub UserService for testing the sequence block.
    """

    def __init__(self,  # pylint: disable=too-many-positional-arguments
                 user=None,
                 user_is_staff=False,
                 user_role=None,
                 anonymous_user_id=None,
                 deprecated_anonymous_user_id=None,
                 request_country_code=None,
                 **kwargs):
        self.user = user
        self.user_is_staff = user_is_staff
        self.user_role = user_role
        self.anonymous_user_id = anonymous_user_id
        self.deprecated_anonymous_user_id = deprecated_anonymous_user_id
        self.request_country_code = request_country_code
        self._django_user = user
        super().__init__(**kwargs)

    def get_current_user(self):
        """
        Implements abstract method for getting the current user.
        """
        user = XBlockUser()
        if self.user and self.user.is_authenticated:
            user.opt_attrs['edx-platform.anonymous_user_id'] = self.anonymous_user_id
            user.opt_attrs['edx-platform.deprecated_anonymous_user_id'] = self.deprecated_anonymous_user_id
            user.opt_attrs['edx-platform.request_country_code'] = self.request_country_code
            user.opt_attrs['edx-platform.user_is_staff'] = self.user_is_staff
            user.opt_attrs['edx-platform.user_id'] = self.user.id
            user.opt_attrs['edx-platform.user_role'] = self.user_role
            user.opt_attrs['edx-platform.username'] = self.user.username
        else:
            user.opt_attrs['edx-platform.username'] = 'anonymous'
            user.opt_attrs['edx-platform.request_country_code'] = self.request_country_code
            user.opt_attrs['edx-platform.is_authenticated'] = False
        return user

    def get_user_by_anonymous_id(self, uid=None):  # pylint: disable=unused-argument
        """
        Return the original user passed into the service.
        """
        return self.user


class MockRuntime(Runtime):  # pylint: disable=abstract-method
    """A mock implementation of the Runtime class for testing purposes."""

    def __init__(self, anonymous_student_id, services=None):
        # id_reader and id_generator are required by Runtime.
        super().__init__(id_reader=lambda: None, id_generator=lambda: None, services=services)
        self.anonymous_student_id = anonymous_student_id

    def handler_url(
        self, block, handler_name, suffix="", query="", thirdparty=False
    ):  # pylint: disable=too-many-positional-arguments
        return f"/mock_url/{handler_name}"

    def local_resource_url(self, block, resource):  # pylint: disable=arguments-renamed
        return f"/mock_resource_url/{resource}"

    def resource_url(self, resource):
        return f"/mock_resource/{resource}"

    def publish(self, block, event_type, event_data):
        pass


def get_test_system(
    user=None,
    user_is_staff=False,
):
    """Construct a minimal test system for the LTIBlockTest."""

    if not user:
        user = Mock(name='get_test_system.user', is_staff=False)
    user_service = StubUserService(
        user=user,
        anonymous_user_id='student',
        deprecated_anonymous_user_id='student',
        user_is_staff=user_is_staff,
        user_role='student',
    )
    runtime = MockRuntime(
        anonymous_student_id="student",
        services={
            "user": user_service,
        }
    )

    return runtime
