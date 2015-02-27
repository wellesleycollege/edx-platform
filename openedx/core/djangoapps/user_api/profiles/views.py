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

from . import PROFILE_VISIBILITY_PREF_KEY, ALL_USERS_VISIBILITY

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

    def get(self, request, username):
        """
        GET /api/user/v0/profiles/{username}/[?include_all={true | false}]

        Note: include_all can only be specified if the user is making the request
        for their own username. It defaults to false, but if true then all the
        profile fields will be returned even for a user with a private profile.
        """
        if request.user.username == username:
            include_all_results = self.request.QUERY_PARAMS.get('include_all') == 'true'
        else:
            include_all_results = False
        profile_settings = ProfileView.get_serialized_profile(
            username,
            settings.PROFILE_CONFIGURATION,
            include_all_results=include_all_results,
        )
        return Response(profile_settings)

    @staticmethod
    def get_serialized_profile(username, configuration, include_all_results=False):
        """
        Returns a JSON representation of the user's profile settings.
        """
        account_settings = AccountView.get_serialized_account(username)
        profile_settings = {}
        privacy_setting = ProfileView._get_user_profile_privacy(username, configuration)
        if include_all_results or privacy_setting == ALL_USERS_VISIBILITY:
            public_field_names = configuration.get('all_fields')
        else:
            public_field_names = configuration.get('public_fields')
        for field_name in public_field_names:
            profile_settings[field_name] = account_settings.get(field_name, None)
        return profile_settings

    @staticmethod
    def _get_user_profile_privacy(username, configuration):
        """
        Returns the profile privacy preference for the specified user.
        """
        user = User.objects.get(username=username)
        profile_privacy = UserPreference.get_preference(user, PROFILE_VISIBILITY_PREF_KEY)
        return profile_privacy if profile_privacy else configuration.get('default_visibility')
