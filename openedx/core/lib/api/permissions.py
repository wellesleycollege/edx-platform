from django.conf import settings
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied
from django.http import Http404


class ApiKeyHeaderPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        """
        Check for permissions by matching the configured API key and header

        If settings.DEBUG is True and settings.EDX_API_KEY is not set or None,
        then allow the request. Otherwise, allow the request if and only if
        settings.EDX_API_KEY is set and the X-Edx-Api-Key HTTP header is
        present in the request and matches the setting.
        """
        api_key = getattr(settings, "EDX_API_KEY", None)
        return (
            (settings.DEBUG and api_key is None) or
            (api_key is not None and request.META.get("HTTP_X_EDX_API_KEY") == api_key)
        )


class ApiKeyHeaderPermissionIsAuthenticated(ApiKeyHeaderPermission, permissions.IsAuthenticated):
    """
    Allow someone to access the view if they have the API key OR they are authenticated.

    See ApiKeyHeaderPermission for more information how the API key portion is implemented.
    """
    def has_permission(self, request, view):
        api_permissions = ApiKeyHeaderPermission.has_permission(self, request, view)
        print "has api permissions: %d" % api_permissions
        is_authenticated_permissions = permissions.IsAuthenticated.has_permission(self, request, view)
        print "has authentication permissions %d" % api_permissions

        return api_permissions or is_authenticated_permissions


class IsAuthenticatedOrDebug(permissions.BasePermission):
    """
    Allows access only to authenticated users, or anyone if debug mode is enabled.
    """

    def has_permission(self, request, view):
        if settings.DEBUG:
            return True

        user = getattr(request, 'user', None)
        return user and user.is_authenticated()


class IsUserInUrl(permissions.BasePermission):
    """
    Permission that checks to see if the request user matches the user in the URL.
    """
    def has_permission(self, request, view):
        # Return a 404 instead of a 403 (Unauthorized). If one user is looking up
        # other users, do not let them deduce the existence of an account.
        if request.user.username != request.parser_context.get('kwargs', {}).get('username', None):
            raise Http404()
        return True


class IsUserInUrlOrStaff(IsUserInUrl):
    """
    Permission that checks to see if the request user matches the user in the URL or has is_staff access.
    """
    def has_permission(self, request, view):
        if request.user.is_staff:
            return True

        return super(IsUserInUrlOrStaff, self).has_permission(request, view)
