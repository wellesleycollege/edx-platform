"""
NOTE: this API is WIP and has not yet been approved. Do not use this API without talking to Christina or Andy.

For more information, see:
https://openedx.atlassian.net/wiki/display/TNL/User+API
"""
from django.conf import settings
from django.contrib.auth.models import User

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.authentication import OAuth2Authentication, SessionAuthentication
from rest_framework import permissions

from ..accounts.views import AccountView
from ..models import UserPreference

from . import PROFILE_VISIBILITY_PREF_KEY

class ProfileView(APIView):
    """
        **Use Cases**

            Get the user's public profile information.

        **Example Requests**:

            GET /api/user/v0/profiles/{username}/

        **Response Values for GET**

            Returns the same responses as for the AccountView API, but filtered based upon
            the user's specified privacy permissions.

    """
    authentication_classes = (OAuth2Authentication, SessionAuthentication)
    permission_classes = (permissions.IsAuthenticated,)

    DEFAULT_PUBLIC_PROFILE_FIELD_NAMES = [
        'username',
    ]

    def get(self, request, username):
        """
        GET /api/user/v0/profiles/{username}/
        """
        account_settings = AccountView.get_serialized_account(username)
        profile_settings = {}
        privacy_setting = self._get_user_profile_privacy(username)
        if privacy_setting == 'edx_users':
            public_field_names = settings.SHARED_PROFILE_PUBLIC_FIELDS
        else:
            public_field_names = settings.PRIVATE_PROFILE_PUBLIC_FIELDS
        for field_name in public_field_names:
            profile_settings[field_name] = account_settings.get(field_name, None)
        return Response(profile_settings)

    def _get_user_profile_privacy(self, username):
        """
        Returns the profile privacy preference for the specified user.
        """
        user = User.objects.get(username=username)
        profile_privacy = UserPreference.get_preference(user, PROFILE_VISIBILITY_PREF_KEY)
        return profile_privacy if profile_privacy else settings.DEFAULT_PROFILE_VISIBILITY
