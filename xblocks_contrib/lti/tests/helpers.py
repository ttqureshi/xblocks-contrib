"""
Utility methods for unit tests.
"""

import datetime
import pytest
import re
from path import Path as path
from xblock.fields import JSONField
from xblock.reference.user_service import UserService, XBlockUser


TIMEDELTA_REGEX = re.compile(r'^((?P<days>\d+?) day(?:s?))?(\s)?((?P<hours>\d+?) hour(?:s?))?(\s)?((?P<minutes>\d+?) minute(?:s)?)?(\s)?((?P<seconds>\d+?) second(?:s)?)?$')  # lint-amnesty, pylint: disable=line-too-long


class Timedelta(JSONField):  # lint-amnesty, pylint: disable=missing-class-docstring
    # Timedeltas are immutable, see http://docs.python.org/2/library/datetime.html#available-types
    MUTABLE = False

    def from_json(self, time_str):  # lint-amnesty, pylint: disable=arguments-differ
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

    def __init__(self,
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
