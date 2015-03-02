"""
Certificates are created for a student and an offering of a course.

When a certificate is generated, a unique ID is generated so that
the certificate can be verified later. The ID is a UUID4, so that
it can't be easily guessed and so that it is unique.

Certificates are generated in batches by a cron job, when a
certificate is available for download the GeneratedCertificate
table is updated with information that will be displayed
on the course overview page.


State diagram:

[deleted,error,unavailable] [error,downloadable]
            +                +             +
            |                |             |
            |                |             |
         add_cert       regen_cert     del_cert
            |                |             |
            v                v             v
       [generating]    [regenerating]  [deleting]
            +                +             +
            |                |             |
       certificate      certificate    certificate
         created       removed,created   deleted
            +----------------+-------------+------->[error]
            |                |             |
            |                |             |
            v                v             v
      [downloadable]   [downloadable]  [deleted]


Eligibility:

    Students are eligible for a certificate if they pass the course
    with the following exceptions:

       If the student has allow_certificate set to False in the student profile
       he will never be issued a certificate.

       If the user and course is present in the certificate whitelist table
       then the student will be issued a certificate regardless of his grade,
       unless he has allow_certificate set to False.
"""
import json

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from datetime import datetime
from model_utils import Choices
from config_models.models import ConfigurationModel
from xmodule_django.models import CourseKeyField, NoneToEmptyManager
from util.milestones_helpers import fulfill_course_milestone


class CertificateStatuses(object):
    deleted = 'deleted'
    deleting = 'deleting'
    downloadable = 'downloadable'
    error = 'error'
    generating = 'generating'
    notpassing = 'notpassing'
    regenerating = 'regenerating'
    restricted = 'restricted'
    unavailable = 'unavailable'


class CertificateWhitelist(models.Model):
    """
    Tracks students who are whitelisted, all users
    in this table will always qualify for a certificate
    regardless of their grade unless they are on the
    embargoed country restriction list
    (allow_certificate set to False in userprofile).
    """

    objects = NoneToEmptyManager()

    user = models.ForeignKey(User)
    course_id = CourseKeyField(max_length=255, blank=True, default=None)
    whitelist = models.BooleanField(default=0)


class GeneratedCertificate(models.Model):

    MODES = Choices('verified', 'honor', 'audit')

    user = models.ForeignKey(User)
    course_id = CourseKeyField(max_length=255, blank=True, default=None)
    verify_uuid = models.CharField(max_length=32, blank=True, default='')
    download_uuid = models.CharField(max_length=32, blank=True, default='')
    download_url = models.CharField(max_length=128, blank=True, default='')
    grade = models.CharField(max_length=5, blank=True, default='')
    key = models.CharField(max_length=32, blank=True, default='')
    distinction = models.BooleanField(default=False)
    status = models.CharField(max_length=32, default='unavailable')
    mode = models.CharField(max_length=32, choices=MODES, default=MODES.honor)
    name = models.CharField(blank=True, max_length=255)
    created_date = models.DateTimeField(
        auto_now_add=True, default=datetime.now)
    modified_date = models.DateTimeField(
        auto_now=True, default=datetime.now)
    error_reason = models.CharField(max_length=512, blank=True, default='')

    class Meta:
        unique_together = (('user', 'course_id'),)

    @classmethod
    def certificate_for_student(cls, student, course_id):
        """
        This returns the certificate for a student for a particular course
        or None if no such certificate exits.
        """
        try:
            return cls.objects.get(user=student, course_id=course_id)
        except cls.DoesNotExist:
            pass

        return None


@receiver(post_save, sender=GeneratedCertificate)
def handle_post_cert_generated(sender, instance, **kwargs):  # pylint: disable=no-self-argument, unused-argument
    """
    Handles post_save signal of GeneratedCertificate, and mark user collected
    course milestone entry if user has passed the course
    or certificate status is 'generating'.
    """
    if settings.FEATURES.get('ENABLE_PREREQUISITE_COURSES') and instance.status == CertificateStatuses.generating:
        fulfill_course_milestone(instance.course_id, instance.user)


def certificate_status_for_student(student, course_id):
    '''
    This returns a dictionary with a key for status, and other information.
    The status is one of the following:

    unavailable  - No entry for this student--if they are actually in
                   the course, they probably have not been graded for
                   certificate generation yet.
    generating   - A request has been made to generate a certificate,
                   but it has not been generated yet.
    regenerating - A request has been made to regenerate a certificate,
                   but it has not been generated yet.
    deleting     - A request has been made to delete a certificate.

    deleted      - The certificate has been deleted.
    downloadable - The certificate is available for download.
    notpassing   - The student was graded but is not passing
    restricted   - The student is on the restricted embargo list and
                   should not be issued a certificate. This will
                   be set if allow_certificate is set to False in
                   the userprofile table

    If the status is "downloadable", the dictionary also contains
    "download_url".

    If the student has been graded, the dictionary also contains their
    grade for the course with the key "grade".
    '''

    try:
        generated_certificate = GeneratedCertificate.objects.get(
            user=student, course_id=course_id)
        d = {'status': generated_certificate.status,
             'mode': generated_certificate.mode}
        if generated_certificate.grade:
            d['grade'] = generated_certificate.grade
        if generated_certificate.status == CertificateStatuses.downloadable:
            d['download_url'] = generated_certificate.download_url

        return d
    except GeneratedCertificate.DoesNotExist:
        pass
    return {'status': CertificateStatuses.unavailable, 'mode': GeneratedCertificate.MODES.honor}


class CertificateGenerationConfiguration(ConfigurationModel):
    """Configure certificate generation."""
    pass


class CertificateHtmlViewConfiguration(ConfigurationModel):
    """
    Static values for certificate HTML view context parameters.
    Default values will be applied across all certificate types (course modes)
    Matching 'mode' overrides will be used instead of defaults, where applicable
    Example configuration :
        {
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
    """
    configuration = models.TextField(
        help_text="Certificate HTML View Parameters (JSON)"
    )

    def clean(self):
        """
        Ensures configuration field contains valid JSON.
        """
        try:
            json.loads(self.configuration)
        except ValueError:
            raise ValidationError('Must be valid JSON string.')

    @classmethod
    def get_config(cls):
        """
        Retrieves the configuration field value from the database
        """
        instance = cls.current()
        json_data = json.loads(instance.configuration) if instance.enabled else {}
        config_path = settings.FEATURES.get('CERTS_HTML_VIEW_CONFIG_PATH')
        if not json_data and config_path:
            try:
                with open(config_path) as json_file:
                    json_data = json.load(json_file)
            except IOError:
                pass
        return json_data
