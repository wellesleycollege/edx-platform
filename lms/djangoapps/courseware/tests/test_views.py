# coding=UTF-8
"""
Tests courseware views.py
"""
import cgi
from datetime import datetime
from pytz import UTC
import unittest
import ddt

from django.conf import settings
from django.contrib.auth.models import User, AnonymousUser
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponseBadRequest
from django.test import TestCase
from django.test.client import RequestFactory
from django.test.utils import override_settings
from certificates import api as certs_api
from certificates.models import CertificateStatuses, CertificateGenerationConfiguration
from certificates.tests.factories import GeneratedCertificateFactory
from edxmako.middleware import MakoMiddleware
from edxmako.tests import mako_middleware_process_request
from mock import MagicMock, patch, create_autospec, Mock
from opaque_keys.edx.locations import Location, SlashSeparatedCourseKey

import courseware.views as views
from xmodule.modulestore.tests.django_utils import (
    TEST_DATA_MOCK_MODULESTORE, TEST_DATA_MIXED_TOY_MODULESTORE
)
from course_modes.models import CourseMode
import shoppingcart
from student.models import CourseEnrollment
from student.tests.factories import AdminFactory, UserFactory
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from util.tests.test_date_utils import fake_ugettext, fake_pgettext
from util.views import ensure_valid_course_key


class TestJumpTo(ModuleStoreTestCase):
    """
    Check the jumpto link for a course.
    """
    MODULESTORE = TEST_DATA_MIXED_TOY_MODULESTORE

    def setUp(self):
        super(TestJumpTo, self).setUp()
        # Use toy course from XML
        self.course_key = SlashSeparatedCourseKey('edX', 'toy', '2012_Fall')

    def test_jumpto_invalid_location(self):
        location = self.course_key.make_usage_key(None, 'NoSuchPlace')
        # This is fragile, but unfortunately the problem is that within the LMS we
        # can't use the reverse calls from the CMS
        jumpto_url = '{0}/{1}/jump_to/{2}'.format('/courses', self.course_key.to_deprecated_string(), location.to_deprecated_string())
        response = self.client.get(jumpto_url)
        self.assertEqual(response.status_code, 404)

    @unittest.skip
    def test_jumpto_from_chapter(self):
        location = self.course_key.make_usage_key('chapter', 'Overview')
        jumpto_url = '{0}/{1}/jump_to/{2}'.format('/courses', self.course_key.to_deprecated_string(), location.to_deprecated_string())
        expected = 'courses/edX/toy/2012_Fall/courseware/Overview/'
        response = self.client.get(jumpto_url)
        self.assertRedirects(response, expected, status_code=302, target_status_code=302)

    @unittest.skip
    def test_jumpto_id(self):
        jumpto_url = '{0}/{1}/jump_to_id/{2}'.format('/courses', self.course_key.to_deprecated_string(), 'Overview')
        expected = 'courses/edX/toy/2012_Fall/courseware/Overview/'
        response = self.client.get(jumpto_url)
        self.assertRedirects(response, expected, status_code=302, target_status_code=302)

    def test_jumpto_id_invalid_location(self):
        location = Location('edX', 'toy', 'NoSuchPlace', None, None, None)
        jumpto_url = '{0}/{1}/jump_to_id/{2}'.format('/courses', self.course_key.to_deprecated_string(), location.to_deprecated_string())
        response = self.client.get(jumpto_url)
        self.assertEqual(response.status_code, 404)


@ddt.ddt
class ViewsTestCase(ModuleStoreTestCase):
    """
    Tests for views.py methods.
    """
    def setUp(self):
        super(ViewsTestCase, self).setUp()
        self.course = CourseFactory.create()
        self.chapter = ItemFactory.create(category='chapter', parent_location=self.course.location)  # pylint: disable=no-member
        self.section = ItemFactory.create(category='sequential', parent_location=self.chapter.location, due=datetime(2013, 9, 18, 11, 30, 00))
        self.vertical = ItemFactory.create(category='vertical', parent_location=self.section.location)
        self.component = ItemFactory.create(category='problem', parent_location=self.vertical.location)

        self.course_key = self.course.id
        self.user = UserFactory(username='dummy', password='123456', email='test@mit.edu')
        self.date = datetime(2013, 1, 22, tzinfo=UTC)
        self.enrollment = CourseEnrollment.enroll(self.user, self.course_key)
        self.enrollment.created = self.date
        self.enrollment.save()
        self.request_factory = RequestFactory()
        chapter = 'Overview'
        self.chapter_url = '%s/%s/%s' % ('/courses', self.course_key, chapter)

        self.org = u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ"
        self.org_html = "<p>'+Stark/Industries+'</p>"

    @unittest.skipUnless(settings.FEATURES.get('ENABLE_SHOPPING_CART'), "Shopping Cart not enabled in settings")
    @patch.dict(settings.FEATURES, {'ENABLE_PAID_COURSE_REGISTRATION': True})
    def test_course_about_in_cart(self):
        in_cart_span = '<span class="add-to-cart">'
        # don't mock this course due to shopping cart existence checking
        course = CourseFactory.create(org="new", number="unenrolled", display_name="course")
        request = self.request_factory.get(reverse('about_course', args=[course.id.to_deprecated_string()]))
        request.user = AnonymousUser()
        response = views.course_about(request, course.id.to_deprecated_string())
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(in_cart_span, response.content)

        # authenticated user with nothing in cart
        request.user = self.user
        response = views.course_about(request, course.id.to_deprecated_string())
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(in_cart_span, response.content)

        # now add the course to the cart
        cart = shoppingcart.models.Order.get_cart_for_user(self.user)
        shoppingcart.models.PaidCourseRegistration.add_to_order(cart, course.id)
        response = views.course_about(request, course.id.to_deprecated_string())
        self.assertEqual(response.status_code, 200)
        self.assertIn(in_cart_span, response.content)

    def test_user_groups(self):
        # depreciated function
        mock_user = MagicMock()
        mock_user.is_authenticated.return_value = False
        self.assertEqual(views.user_groups(mock_user), [])

    def test_get_current_child(self):
        self.assertIsNone(views.get_current_child(MagicMock()))
        mock_xmodule = MagicMock()
        mock_xmodule.position = -1
        mock_xmodule.get_display_items.return_value = ['one', 'two']
        self.assertEqual(views.get_current_child(mock_xmodule), 'one')
        mock_xmodule_2 = MagicMock()
        mock_xmodule_2.position = 3
        mock_xmodule_2.get_display_items.return_value = []
        self.assertIsNone(views.get_current_child(mock_xmodule_2))

    def test_redirect_to_course_position(self):
        mock_module = MagicMock()
        mock_module.descriptor.id = 'Underwater Basketweaving'
        mock_module.position = 3
        mock_module.get_display_items.return_value = []
        self.assertRaises(Http404, views.redirect_to_course_position,
                          mock_module, views.CONTENT_DEPTH)

    def test_invalid_course_id(self):
        response = self.client.get('/courses/MITx/3.091X/')
        self.assertEqual(response.status_code, 404)

    def test_incomplete_course_id(self):
        response = self.client.get('/courses/MITx/')
        self.assertEqual(response.status_code, 404)

    def test_index_invalid_position(self):
        request_url = '/'.join([
            '/courses',
            self.course.id.to_deprecated_string(),
            'courseware',
            self.chapter.location.name,
            self.section.location.name,
            'f'
        ])
        self.client.login(username=self.user.username, password="123456")
        response = self.client.get(request_url)
        self.assertEqual(response.status_code, 404)

    @unittest.skip
    def test_unicode_handling_in_url(self):
        url_parts = [
            '/courses',
            self.course.id.to_deprecated_string(),
            'courseware',
            self.chapter.location.name,
            self.section.location.name,
            '1'
        ]
        self.client.login(username=self.user.username, password="123456")
        for idx, val in enumerate(url_parts):
            url_parts_copy = url_parts[:]
            url_parts_copy[idx] = val + u'χ'
            request_url = '/'.join(url_parts_copy)
            response = self.client.get(request_url)
            self.assertEqual(response.status_code, 404)

    def test_registered_for_course(self):
        self.assertFalse(views.registered_for_course('Basketweaving', None))
        mock_user = MagicMock()
        mock_user.is_authenticated.return_value = False
        self.assertFalse(views.registered_for_course('dummy', mock_user))
        mock_course = MagicMock()
        mock_course.id = self.course_key
        self.assertTrue(views.registered_for_course(mock_course, self.user))

    @override_settings(PAID_COURSE_REGISTRATION_CURRENCY=["USD", "$"])
    def test_get_cosmetic_display_price(self):
        """
        Check that get_cosmetic_display_price() returns the correct price given its inputs.
        """
        registration_price = 99
        self.course.cosmetic_display_price = 10
        # Since registration_price is set, it overrides the cosmetic_display_price and should be returned
        self.assertEqual(views.get_cosmetic_display_price(self.course, registration_price), "$99")

        registration_price = 0
        # Since registration_price is not set, cosmetic_display_price should be returned
        self.assertEqual(views.get_cosmetic_display_price(self.course, registration_price), "$10")

        self.course.cosmetic_display_price = 0
        # Since both prices are not set, there is no price, thus "Free"
        self.assertEqual(views.get_cosmetic_display_price(self.course, registration_price), "Free")

    def test_jump_to_invalid(self):
        # TODO add a test for invalid location
        # TODO add a test for no data *
        request = self.request_factory.get(self.chapter_url)
        self.assertRaisesRegexp(Http404, 'Invalid course_key or usage_key', views.jump_to,
                                request, 'bar', ())

    @unittest.skip
    def test_no_end_on_about_page(self):
        # Toy course has no course end date or about/end_date blob
        self.verify_end_date('edX/toy/TT_2012_Fall')

    @unittest.skip
    def test_no_end_about_blob(self):
        # test_end has a course end date, no end_date HTML blob
        self.verify_end_date("edX/test_end/2012_Fall", "Sep 17, 2015")

    @unittest.skip
    def test_about_blob_end_date(self):
        # test_about_blob_end_date has both a course end date and an end_date HTML blob.
        # HTML blob wins
        self.verify_end_date("edX/test_about_blob_end_date/2012_Fall", "Learning never ends")

    def verify_end_date(self, course_id, expected_end_text=None):
        """
        Visits the about page for `course_id` and tests that both the text "Classes End", as well
        as the specified `expected_end_text`, is present on the page.

        If `expected_end_text` is None, verifies that the about page *does not* contain the text
        "Classes End".
        """
        request = self.request_factory.get("foo")
        request.user = self.user

        # TODO: Remove the dependency on MakoMiddleware (by making the views explicitly supply a RequestContext)
        MakoMiddleware().process_request(request)

        result = views.course_about(request, course_id)
        if expected_end_text is not None:
            self.assertContains(result, "Classes End")
            self.assertContains(result, expected_end_text)
        else:
            self.assertNotContains(result, "Classes End")

    def test_chat_settings(self):
        mock_user = MagicMock()
        mock_user.username = "johndoe"

        mock_course = MagicMock()
        mock_course.id = "a/b/c"

        # Stub this out in the case that it's not in the settings
        domain = "jabber.edx.org"
        settings.JABBER_DOMAIN = domain

        chat_settings = views.chat_settings(mock_course, mock_user)

        # Test the proper format of all chat settings
        self.assertEqual(chat_settings['domain'], domain)
        self.assertEqual(chat_settings['room'], "a-b-c_class")
        self.assertEqual(chat_settings['username'], "johndoe@%s" % domain)

        # TODO: this needs to be changed once we figure out how to
        #       generate/store a real password.
        self.assertEqual(chat_settings['password'], "johndoe@%s" % domain)

    @patch.dict(settings.FEATURES, {'ENABLE_MKTG_EMAIL_OPT_IN': True})
    def test_course_mktg_about_coming_soon(self):
        # We should not be able to find this course
        url = reverse('mktg_about_course', kwargs={'course_id': 'no/course/here'})
        response = self.client.get(url, {'org': self.org})
        self.assertIn('Coming Soon', response.content)

        # Verify that the checkbox is not displayed
        self._email_opt_in_checkbox(response)

    @patch.dict(settings.FEATURES, {'ENABLE_MKTG_EMAIL_OPT_IN': True})
    @ddt.data(
        # One organization name
        (u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ", u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ"),
        # Two organization names
        (",".join([u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ"] * 2), u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ" + " and " + u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ"),
        # Three organization names
        (",".join([u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ"] * 3), u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ" + ", " + u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ" + ", " + "and " + u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ")
    )
    @ddt.unpack
    def test_course_mktg_register(self, org, org_name_string):
        response = self._load_mktg_about(org=org)
        self.assertIn('Enroll in', response.content)
        self.assertNotIn('and choose your student track', response.content)

        # Verify that the checkbox is displayed
        self._email_opt_in_checkbox(response, org_name_string)

    @patch.dict(settings.FEATURES, {'ENABLE_MKTG_EMAIL_OPT_IN': True})
    @ddt.data(
        # One organization name
        (u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ", u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ"),
        # Two organization names
        (",".join([u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ"] * 2), u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ" + " and " + u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ"),
        # Three organization names
        (",".join([u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ"] * 3), u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ" + ", " + u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ" + ", " + "and " + u"ꜱᴛᴀʀᴋ ɪɴᴅᴜꜱᴛʀɪᴇꜱ")
    )
    @ddt.unpack
    def test_course_mktg_register_multiple_modes(self, org, org_name_string):
        CourseMode.objects.get_or_create(
            mode_slug='honor',
            mode_display_name='Honor Code Certificate',
            course_id=self.course_key
        )
        CourseMode.objects.get_or_create(
            mode_slug='verified',
            mode_display_name='Verified Certificate',
            course_id=self.course_key
        )

        response = self._load_mktg_about(org=org)
        self.assertIn('Enroll in', response.content)
        self.assertIn('and choose your student track', response.content)

        # Verify that the checkbox is displayed
        self._email_opt_in_checkbox(response, org_name_string)

        # clean up course modes
        CourseMode.objects.all().delete()

    @patch.dict(settings.FEATURES, {'ENABLE_MKTG_EMAIL_OPT_IN': True})
    def test_course_mktg_no_organization_name(self):
        # Don't pass an organization name as a GET parameter, even though the email
        # opt-in feature is enabled.
        response = response = self._load_mktg_about()

        # Verify that the checkbox is not displayed
        self._email_opt_in_checkbox(response)

    @patch.dict(settings.FEATURES, {'ENABLE_MKTG_EMAIL_OPT_IN': False})
    def test_course_mktg_opt_in_disabled(self):
        # Pass an organization name as a GET parameter, even though the email
        # opt-in feature is disabled.
        response = self._load_mktg_about(org=self.org)

        # Verify that the checkbox is not displayed
        self._email_opt_in_checkbox(response)

    @patch.dict(settings.FEATURES, {'ENABLE_MKTG_EMAIL_OPT_IN': True})
    def test_course_mktg_organization_html(self):
        response = self._load_mktg_about(org=self.org_html)

        # Verify that the checkbox is displayed with the organization name
        # in the label escaped as expected.
        self._email_opt_in_checkbox(response, cgi.escape(self.org_html))

    @patch.dict(settings.FEATURES, {
        'IS_EDX_DOMAIN': True,
        'ENABLE_MKTG_EMAIL_OPT_IN': True
    })
    def test_mktg_about_language_edx_domain(self):
        # Since we're in an edx-controlled domain, and our marketing site
        # supports only English, override the language setting
        # and use English.
        response = self._load_mktg_about(language='eo', org=self.org_html)
        self.assertContains(response, "Enroll in")
        self.assertContains(response, "and learn about its other programs")

    @patch.dict(settings.FEATURES, {'IS_EDX_DOMAIN': False})
    def test_mktg_about_language_openedx(self):
        # If we're in an OpenEdX installation,
        # may want to support languages other than English,
        # so respect the language code.
        response = self._load_mktg_about(language='eo')
        self.assertContains(response, u"Énröll ïn".encode('utf-8'))

    def test_submission_history_accepts_valid_ids(self):
        # log into a staff account
        admin = AdminFactory()

        self.client.login(username=admin.username, password='test')

        url = reverse('submission_history', kwargs={
            'course_id': self.course_key.to_deprecated_string(),
            'student_username': 'dummy',
            'location': self.component.location.to_deprecated_string(),
        })
        response = self.client.get(url)
        # Tests that we do not get an "Invalid x" response when passing correct arguments to view
        self.assertFalse('Invalid' in response.content)

    def test_submission_history_xss(self):
        # log into a staff account
        admin = AdminFactory()

        self.client.login(username=admin.username, password='test')

        # try it with an existing user and a malicious location
        url = reverse('submission_history', kwargs={
            'course_id': self.course_key.to_deprecated_string(),
            'student_username': 'dummy',
            'location': '<script>alert("hello");</script>'
        })
        response = self.client.get(url)
        self.assertFalse('<script>' in response.content)

        # try it with a malicious user and a non-existent location
        url = reverse('submission_history', kwargs={
            'course_id': self.course_key.to_deprecated_string(),
            'student_username': '<script>alert("hello");</script>',
            'location': 'dummy'
        })
        response = self.client.get(url)
        self.assertFalse('<script>' in response.content)

    def _load_mktg_about(self, language=None, org=None):
        """Retrieve the marketing about button (iframed into the marketing site)
        and return the HTTP response.

        Keyword Args:
            language (string): If provided, send this in the 'Accept-Language' HTTP header.
            org (string): If provided, send the string as a GET parameter.

        Returns:
            Response

        """
        # Log in as an administrator to guarantee that we can access the button
        admin = AdminFactory()
        self.client.login(username=admin.username, password='test')

        # If provided, set the language header
        headers = {}
        if language is not None:
            headers['HTTP_ACCEPT_LANGUAGE'] = language

        url = reverse('mktg_about_course', kwargs={'course_id': unicode(self.course_key)})
        if org:
            return self.client.get(url, {'org': org}, **headers)
        else:
            return self.client.get(url, **headers)

    def _email_opt_in_checkbox(self, response, org_name_string=None):
        """Check if the email opt-in checkbox appears in the response content."""
        checkbox_html = '<input id="email-opt-in" type="checkbox" name="opt-in" class="email-opt-in" value="true" checked>'
        if org_name_string:
            # Verify that the email opt-in checkbox appears, and that the expected
            # organization name is displayed.
            self.assertContains(response, checkbox_html, html=True)
            self.assertContains(response, org_name_string)
        else:
            # Verify that the email opt-in checkbox does not appear
            self.assertNotContains(response, checkbox_html, html=True)


# setting TIME_ZONE_DISPLAYED_FOR_DEADLINES explicitly
@override_settings(TIME_ZONE_DISPLAYED_FOR_DEADLINES="UTC")
class BaseDueDateTests(ModuleStoreTestCase):
    """
    Base class that verifies that due dates are rendered correctly on a page
    """
    __test__ = False

    def get_text(self, course):  # pylint: disable=unused-argument
        """Return the rendered text for the page to be verified"""
        raise NotImplementedError

    def set_up_course(self, **course_kwargs):
        """
        Create a stock course with a specific due date.

        :param course_kwargs: All kwargs are passed to through to the :class:`CourseFactory`
        """
        course = CourseFactory.create(**course_kwargs)
        chapter = ItemFactory.create(category='chapter', parent_location=course.location)  # pylint: disable=no-member
        section = ItemFactory.create(category='sequential', parent_location=chapter.location, due=datetime(2013, 9, 18, 11, 30, 00))
        vertical = ItemFactory.create(category='vertical', parent_location=section.location)
        ItemFactory.create(category='problem', parent_location=vertical.location)

        course = modulestore().get_course(course.id)  # pylint: disable=no-member
        self.assertIsNotNone(course.get_children()[0].get_children()[0].due)
        return course

    def setUp(self):
        super(BaseDueDateTests, self).setUp()
        self.request_factory = RequestFactory()
        self.user = UserFactory.create()
        self.request = self.request_factory.get("foo")
        self.request.user = self.user

        self.time_with_tz = "due Sep 18, 2013 at 11:30 UTC"
        self.time_without_tz = "due Sep 18, 2013 at 11:30"

    def test_backwards_compatability(self):
        # The test course being used has show_timezone = False in the policy file
        # (and no due_date_display_format set). This is to test our backwards compatibility--
        # in course_module's init method, the date_display_format will be set accordingly to
        # remove the timezone.
        course = self.set_up_course(due_date_display_format=None, show_timezone=False)
        text = self.get_text(course)
        self.assertIn(self.time_without_tz, text)
        self.assertNotIn(self.time_with_tz, text)
        # Test that show_timezone has been cleared (which means you get the default value of True).
        self.assertTrue(course.show_timezone)

    def test_defaults(self):
        course = self.set_up_course()
        text = self.get_text(course)
        self.assertIn(self.time_with_tz, text)

    def test_format_none(self):
        # Same for setting the due date to None
        course = self.set_up_course(due_date_display_format=None)
        text = self.get_text(course)
        self.assertIn(self.time_with_tz, text)

    def test_format_plain_text(self):
        # plain text due date
        course = self.set_up_course(due_date_display_format="foobar")
        text = self.get_text(course)
        self.assertNotIn(self.time_with_tz, text)
        self.assertIn("due foobar", text)

    def test_format_date(self):
        # due date with no time
        course = self.set_up_course(due_date_display_format=u"%b %d %y")
        text = self.get_text(course)
        self.assertNotIn(self.time_with_tz, text)
        self.assertIn("due Sep 18 13", text)

    def test_format_hidden(self):
        # hide due date completely
        course = self.set_up_course(due_date_display_format=u"")
        text = self.get_text(course)
        self.assertNotIn("due ", text)

    def test_format_invalid(self):
        # improperly formatted due_date_display_format falls through to default
        # (value of show_timezone does not matter-- setting to False to make that clear).
        course = self.set_up_course(due_date_display_format=u"%%%", show_timezone=False)
        text = self.get_text(course)
        self.assertNotIn("%%%", text)
        self.assertIn(self.time_with_tz, text)


class TestProgressDueDate(BaseDueDateTests):
    """
    Test that the progress page displays due dates correctly
    """
    __test__ = True

    def get_text(self, course):
        """ Returns the HTML for the progress page """

        mako_middleware_process_request(self.request)
        return views.progress(self.request, course_id=course.id.to_deprecated_string(), student_id=self.user.id).content


class TestAccordionDueDate(BaseDueDateTests):
    """
    Test that the accordion page displays due dates correctly
    """
    __test__ = True

    def get_text(self, course):
        """ Returns the HTML for the accordion """
        return views.render_accordion(
            self.request, course, course.get_children()[0].scope_ids.usage_id.to_deprecated_string(),
            None, None
        )


class StartDateTests(ModuleStoreTestCase):
    """
    Test that start dates are properly localized and displayed on the student
    dashboard.
    """

    def setUp(self):
        super(StartDateTests, self).setUp()
        self.request_factory = RequestFactory()
        self.user = UserFactory.create()
        self.request = self.request_factory.get("foo")
        self.request.user = self.user

    def set_up_course(self):
        """
        Create a stock course with a specific due date.

        :param course_kwargs: All kwargs are passed to through to the :class:`CourseFactory`
        """
        course = CourseFactory.create(start=datetime(2013, 9, 16, 7, 17, 28))
        course = modulestore().get_course(course.id)  # pylint: disable=no-member
        return course

    def get_about_text(self, course_key):
        """
        Get the text of the /about page for the course.
        """
        text = views.course_about(self.request, course_key.to_deprecated_string()).content
        return text

    @patch('util.date_utils.pgettext', fake_pgettext(translations={
        ("abbreviated month name", "Sep"): "SEPTEMBER",
    }))
    @patch('util.date_utils.ugettext', fake_ugettext(translations={
        "SHORT_DATE_FORMAT": "%Y-%b-%d",
    }))
    def test_format_localized_in_studio_course(self):
        course = self.set_up_course()
        text = self.get_about_text(course.id)
        # The start date is set in the set_up_course function above.
        self.assertIn("2013-SEPTEMBER-16", text)

    @patch('util.date_utils.pgettext', fake_pgettext(translations={
        ("abbreviated month name", "Jul"): "JULY",
    }))
    @patch('util.date_utils.ugettext', fake_ugettext(translations={
        "SHORT_DATE_FORMAT": "%Y-%b-%d",
    }))
    @unittest.skip
    def test_format_localized_in_xml_course(self):
        text = self.get_about_text(SlashSeparatedCourseKey('edX', 'toy', 'TT_2012_Fall'))
        # The start date is set in common/test/data/two_toys/policies/TT_2012_Fall/policy.json
        self.assertIn("2015-JULY-17", text)


class ProgressPageTests(ModuleStoreTestCase):
    """
    Tests that verify that the progress page works correctly.
    """

    def setUp(self):
        super(ProgressPageTests, self).setUp()
        self.request_factory = RequestFactory()
        self.user = UserFactory.create()
        self.request = self.request_factory.get("foo")
        self.request.user = self.user

        MakoMiddleware().process_request(self.request)

        course = CourseFactory.create(
            start=datetime(2013, 9, 16, 7, 17, 28),
            grade_cutoffs={u'çü†øƒƒ': 0.75, 'Pass': 0.5},
        )
        self.course = modulestore().get_course(course.id)  # pylint: disable=no-member

        self.chapter = ItemFactory.create(category='chapter', parent_location=self.course.location)  # pylint: disable=no-member
        self.section = ItemFactory.create(category='sequential', parent_location=self.chapter.location)
        self.vertical = ItemFactory.create(category='vertical', parent_location=self.section.location)

    def test_pure_ungraded_xblock(self):
        ItemFactory.create(category='acid', parent_location=self.vertical.location)

        resp = views.progress(self.request, course_id=self.course.id.to_deprecated_string())
        self.assertEqual(resp.status_code, 200)

    def test_non_asci_grade_cutoffs(self):
        resp = views.progress(self.request, course_id=self.course.id.to_deprecated_string())
        self.assertEqual(resp.status_code, 200)

    def test_generate_cert_config(self):
        resp = views.progress(self.request, course_id=unicode(self.course.id))
        self.assertNotContains(resp, 'Create Your Certificate')

        # Enable the feature, but do not enable it for this course
        CertificateGenerationConfiguration(enabled=True).save()
        resp = views.progress(self.request, course_id=unicode(self.course.id))
        self.assertNotContains(resp, 'Create Your Certificate')

        # Enable certificate generation for this course
        certs_api.set_cert_generation_enabled(self.course.id, True)
        resp = views.progress(self.request, course_id=unicode(self.course.id))
        self.assertContains(resp, 'Create Your Certificate')


class VerifyCourseKeyDecoratorTests(TestCase):
    """
    Tests for the ensure_valid_course_key decorator.
    """

    def setUp(self):
        super(VerifyCourseKeyDecoratorTests, self).setUp()

        self.request = RequestFactory().get("foo")
        self.valid_course_id = "edX/test/1"
        self.invalid_course_id = "edX/"

    def test_decorator_with_valid_course_id(self):
        mocked_view = create_autospec(views.course_about)
        view_function = ensure_valid_course_key(mocked_view)
        view_function(self.request, course_id=self.valid_course_id)
        self.assertTrue(mocked_view.called)

    def test_decorator_with_invalid_course_id(self):
        mocked_view = create_autospec(views.course_about)
        view_function = ensure_valid_course_key(mocked_view)
        self.assertRaises(Http404, view_function, self.request, course_id=self.invalid_course_id)
        self.assertFalse(mocked_view.called)


class IsCoursePassedTests(ModuleStoreTestCase):
    """
    Tests for the is_course_passed helper function
    """

    def setUp(self):
        super(IsCoursePassedTests, self).setUp()

        self.student = UserFactory()
        self.course = CourseFactory.create(
            org='edx',
            number='verified',
            display_name='Verified Course',
            grade_cutoffs={'cutoff': 0.75, 'Pass': 0.5}
        )
        self.request = RequestFactory()

    def test_user_fails_if_not_clear_exam(self):
        # If user has not grade then false will return
        self.assertFalse(views.is_course_passed(self.course, None, self.student, self.request))

    @patch('courseware.grades.grade', Mock(return_value={'percent': 0.9}))
    def test_user_pass_if_percent_appears_above_passing_point(self):
        # Mocking the grades.grade
        # If user has above passing marks then True will return
        self.assertTrue(views.is_course_passed(self.course, None, self.student, self.request))

    @patch('courseware.grades.grade', Mock(return_value={'percent': 0.2}))
    def test_user_fail_if_percent_appears_below_passing_point(self):
        # Mocking the grades.grade
        # If user has below passing marks then False will return
        self.assertFalse(views.is_course_passed(self.course, None, self.student, self.request))


class GenerateUserCertTests(ModuleStoreTestCase):
    """
    Tests for the view function Generated User Certs
    """

    def setUp(self):
        super(GenerateUserCertTests, self).setUp()

        self.student = UserFactory(username='dummy', password='123456', email='test@mit.edu')
        self.course = CourseFactory.create(
            org='edx',
            number='verified',
            display_name='Verified Course',
            grade_cutoffs={'cutoff': 0.75, 'Pass': 0.5}
        )
        self.enrollment = CourseEnrollment.enroll(self.student, self.course.id, mode='honor')
        self.request = RequestFactory()
        self.client.login(username=self.student, password='123456')
        self.url = reverse('generate_user_cert', kwargs={'course_id': unicode(self.course.id)})

    def test_user_with_out_passing_grades(self):
        # If user has no grading then json will return failed message and badrequest code
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, HttpResponseBadRequest.status_code)
        self.assertIn("Your certificate will be available when you pass the course.", resp.content)

    @patch('courseware.grades.grade', Mock(return_value={'grade': 'Pass', 'percent': 0.75}))
    @override_settings(CERT_QUEUE='certificates', SEGMENT_IO_LMS_KEY="foobar", FEATURES={'SEGMENT_IO_LMS': True})
    def test_user_with_passing_grade(self):
        # If user has above passing grading then json will return cert generating message and
        # status valid code
        # mocking xqueue and analytics

        analytics_patcher = patch('courseware.views.analytics')
        mock_tracker = analytics_patcher.start()
        self.addCleanup(analytics_patcher.stop)

        with patch('capa.xqueue_interface.XQueueInterface.send_to_queue') as mock_send_to_queue:
            mock_send_to_queue.return_value = (0, "Successfully queued")
            resp = self.client.post(self.url)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("Creating certificate", resp.content)

            #Verify Google Analytics event fired after generating certificate
            mock_tracker.track.assert_called_once_with(  # pylint: disable=no-member
                self.student.id,  # pylint: disable=no-member
                'edx.bi.user.certificate.generate',
                {
                    'category': 'certificates',
                    'label': unicode(self.course.id)
                },

                context={
                    'Google Analytics':
                    {'clientId': None}
                }
            )
            mock_tracker.reset_mock()

    @patch('courseware.grades.grade', Mock(return_value={'grade': 'Pass', 'percent': 0.75}))
    def test_user_with_passing_existing_generating_cert(self):
        # If user has passing grade but also has existing generating cert
        # then json will return cert generating message with bad request code
        GeneratedCertificateFactory.create(
            user=self.student,
            course_id=self.course.id,
            status=CertificateStatuses.generating,
            mode='verified'
        )
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, HttpResponseBadRequest.status_code)
        self.assertIn("Creating certificate", resp.content)

    @patch('courseware.grades.grade', Mock(return_value={'grade': 'Pass', 'percent': 0.75}))
    def test_user_with_passing_existing_downloadable_cert(self):
        # If user has passing grade but also has existing downloadable cert
        # then json will return cert generating message with bad request code
        GeneratedCertificateFactory.create(
            user=self.student,
            course_id=self.course.id,
            status=CertificateStatuses.downloadable,
            mode='verified'
        )
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, HttpResponseBadRequest.status_code)
        self.assertIn("Creating certificate", resp.content)

    def test_user_with_non_existing_course(self):
        # If try to access a course with valid key pattern then it will return
        # bad request code with course is not valid message
        resp = self.client.post('/courses/def/abc/in_valid/generate_user_cert')
        self.assertEqual(resp.status_code, HttpResponseBadRequest.status_code)
        self.assertIn("Course is not valid", resp.content)

    def test_user_with_invalid_course_id(self):
        # If try to access a course with invalid key pattern then 404 will return
        resp = self.client.post('/courses/def/generate_user_cert')
        self.assertEqual(resp.status_code, 404)

    def test_user_without_login_return_error(self):
        # If user try to access without login should see a bad request status code with message
        self.client.logout()
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, HttpResponseBadRequest.status_code)
        self.assertIn("You must be signed in to {platform_name} to create a certificate.".format(
            platform_name=settings.PLATFORM_NAME
        ), resp.content)
