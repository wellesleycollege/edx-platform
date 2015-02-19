"""
Tests for the Video Branding configuration.
"""
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.test.utils import override_settings

from certificates.models import CertificateHtmlViewConfiguration

FEATURES_INVALID_FILE_PATH = settings.FEATURES.copy()
FEATURES_INVALID_FILE_PATH['CERTS_HTML_VIEW_CONFIG_PATH'] = 'invalid/path/to/config.json'


class CertificateHtmlViewConfigurationTest(TestCase):
    """
    Test the CertificateHtmlViewConfiguration model.
    """
    def setUp(self):
        super(CertificateHtmlViewConfigurationTest, self).setUp()
        self.configuration_string = """{
            "default": {
                "url": "http://www.edx.org",
                "logo_src": "http://www.edx.org/static/images/logo.png",
                "logo_alt": "Valid Certificate"
            },
            "honor": {
                "logo_src": "http://www.edx.org/static/images/honor-logo.png",
                "logo_alt": "Honor Certificate"
            }
        }"""
        self.config = CertificateHtmlViewConfiguration(configuration=self.configuration_string)

    def test_create(self):
        """
        Tests creation of configuration.
        """
        self.config.save()
        self.assertEquals(self.config.configuration, self.configuration_string)

    def test_clean_bad_json(self):
        """
        Tests if bad JSON string was given.
        """
        self.config = CertificateHtmlViewConfiguration(configuration='{"bad":"test"')
        self.assertRaises(ValidationError, self.config.clean)

    def test_get(self):
        """
        Tests get configuration from saved string.
        """
        self.config.enabled = True
        self.config.save()
        expected_config = {
            "default": {
                "url": "http://www.edx.org",
                "logo_src": "http://www.edx.org/static/images/logo.png",
                "logo_alt": "Valid Certificate"
            },
            "honor": {
                "logo_src": "http://www.edx.org/static/images/honor-logo.png",
                "logo_alt": "Honor Certificate"
            }
        }
        self.assertEquals(self.config.get_config(), expected_config)

    def test_get_not_enabled_uses_file(self):
        """
        Tests get configuration that is not enabled.
        """
        self.config.enabled = False
        self.config.save()
        file_name = '{}/envs/certificates_html_view.json'.format(settings.PROJECT_ROOT)
        with open(file_name) as json_file:
            json_data = json.load(json_file)
        self.assertEquals(self.config.get_config(), json_data)

    @override_settings(FEATURES=FEATURES_INVALID_FILE_PATH)
    def test_get_no_database_no_file(self):
        """
        Tests get configuration that is not enabled.
        """
        self.config.configuration = ''
        self.config.save()
        self.assertEquals(self.config.get_config(), {})
