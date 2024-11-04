"""
Utility methods for unit tests.
"""


import pytest
from path import Path as path
from xblock.reference.user_service import UserService, XBlockUser


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
