# -*- coding: utf-8 -*-
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
from datetime import datetime
import uuid

from django.contrib.auth.models import User
from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from django.utils.translation import ugettext_lazy
from model_utils import Choices
from model_utils.models import TimeStampedModel
from config_models.models import ConfigurationModel
from xmodule_django.models import CourseKeyField, NoneToEmptyManager
from util.milestones_helpers import fulfill_course_milestone
from course_modes.models import CourseMode


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


class ExampleCertificateSet(TimeStampedModel):
    """A set of example certificates.

    Example certificates are used to verify that certificate
    generation is working for a particular course.

    A particular course may have several kinds of certificates
    (e.g. honor and verified), in which case we generate
    multiple example certificates for the course.

    """
    course_key = CourseKeyField(max_length=255, db_index=True)

    class Meta:  # pylint: disable=missing-docstring, old-style-class
        get_latest_by = 'created'

    @classmethod
    @transaction.commit_on_success
    def create_example_set(cls, course_key):
        """Create a set of example certificates for a course.

        Arguments:
            course_key (CourseKey)

        Returns:
            ExampleCertificateSet

        """
        cert_set = cls.objects.create(course_key=course_key)

        ExampleCertificate.objects.bulk_create([
            ExampleCertificate(
                example_cert_set=cert_set,
                description=mode.slug,
                template=cls._template_for_mode(mode.slug, course_key)
            )
            for mode in CourseMode.modes_for_course(course_key)
        ])

        return cert_set

    @classmethod
    def latest_status(cls, course_key):
        """Summarize the latest status of example certificates for a course.

        Arguments:
            course_key (CourseKey)

        Returns:
            list: List of status dictionaries.  If no example certificates
                have been started yet, returns None.

        """
        try:
            latest = cls.objects.filter(course_key=course_key).latest()
        except cls.DoesNotExist:
            return None

        queryset = ExampleCertificate.objects.filter(example_cert_set=latest).order_by('-created')
        return [cert.status_dict for cert in queryset]

    def __iter__(self):
        """Iterate through example certificates in the set.

        Yields:
            ExampleCertificate

        """
        queryset = (ExampleCertificate.objects).select_related('example_cert_set').filter(example_cert_set=self)
        for cert in queryset:
            yield cert

    @staticmethod
    def _template_for_mode(mode_slug, course_key):
        """Calculate the template PDF based on the course mode. """
        return (
            u"certificate-template-{key.org}-{key.course}-verified.pdf".format(key=course_key)
            if mode_slug == 'verified'
            else u"certificate-template-{key.org}-{key.course}.pdf".format(key=course_key)
        )


def _make_uuid():
    """Return a 32-character UUID. """
    return uuid.uuid4().hex


class ExampleCertificate(TimeStampedModel):
    """Example certificate.

    Example certificates are used to verify that certificate
    generation is working for a particular course.

    An example certificate is similar to an ordinary certificate,
    except that:

    1) Example certificates are not associated with a particular user,
        and are never displayed to students.

    2) We store the "inputs" for generating the example certificate
        to make it easier to debug when certificate generation fails.

    3) We use dummy values.

    """
    # Statuses
    STATUS_STARTED = 'started'
    STATUS_SUCCESS = 'success'
    STATUS_ERROR = 'error'

    # Dummy full name for the generated certificate
    EXAMPLE_FULL_NAME = u'John Doë'

    example_cert_set = models.ForeignKey(ExampleCertificateSet)

    description = models.CharField(
        max_length=255,
        help_text=ugettext_lazy(
            u"A human-readable description of the example certificate.  "
            u"For example, 'verified' or 'honor' to differentiate between "
            u"two types of certificates."
        )
    )

    # Inputs to certificate generation
    # We store this for auditing purposes if certificate
    # generation fails.
    uuid = models.CharField(
        max_length=255,
        default=_make_uuid,
        db_index=True,
        unique=True,
        help_text=ugettext_lazy(
            u"A unique identifier for the example certificate.  "
            u"This is used when we receive a response from the queue "
            u"to determine which example certificate was processed."
        )
    )

    access_key = models.CharField(
        max_length=255,
        default=_make_uuid,
        db_index=True,
        help_text=ugettext_lazy(
            u"An access key for the example certificate.  "
            u"This is used when we receive a response from the queue "
            u"to validate that the sender is the same entity we asked "
            u"to generate the certificate."
        )
    )

    full_name = models.CharField(
        max_length=255,
        default=EXAMPLE_FULL_NAME,
        help_text=ugettext_lazy(u"The full name that will appear on the certificate.")
    )

    template = models.CharField(
        max_length=255,
        help_text=ugettext_lazy(u"The template file to use when generating the certificate.")
    )

    # Outputs from certificate generation
    status = models.CharField(
        max_length=255,
        default=STATUS_STARTED,
        choices=(
            (STATUS_STARTED, 'Started'),
            (STATUS_SUCCESS, 'Success'),
            (STATUS_ERROR, 'Error')
        ),
        help_text=ugettext_lazy(u"The status of the example certificate.")
    )

    error_reason = models.TextField(
        null=True,
        default=None,
        help_text=ugettext_lazy(u"The reason an error occurred during certificate generation.")
    )

    download_url = models.CharField(
        max_length=255,
        null=True,
        default=None,
        help_text=ugettext_lazy(u"The download URL for the generated certificate.")
    )

    def update_status(self, status, error_reason=None, download_url=None):
        """Update the status of the example certificate.

        This will usually be called either:
        1) When an error occurs adding the certificate to the queue.
        2) When we receieve a response from the queue (either error or success).

        If an error occurs, we store the error message;
        if certificate generation is successful, we store the URL
        for the generated certificate.

        Arguments:
            status (str): Either `STATUS_SUCCESS` or `STATUS_ERROR`

        Keyword Arguments:
            error_reason (unicode): A description of the error that occurred.
            download_url (unicode): The URL for the generated certificate.

        Raises:
            ValueError: The status is not a valid value.

        """
        if status not in [self.STATUS_SUCCESS, self.STATUS_ERROR]:
            msg = u"Invalid status: must be either '{success}' or '{error}'.".format(
                success=self.STATUS_SUCCESS,
                error=self.STATUS_ERROR
            )
            raise ValueError(msg)

        self.status = status

        if status == self.STATUS_ERROR and error_reason:
            self.error_reason = error_reason

        if status == self.STATUS_SUCCESS and download_url:
            self.download_url = download_url

        self.save()

    @property
    def status_dict(self):
        """Summarize the status of the example certificate.

        Returns:
            dict

        """
        result = {
            'description': self.description,
            'status': self.status,
        }

        if self.error_reason:
            result['error_reason'] = self.error_reason

        if self.download_url:
            result['download_url'] = self.download_url

        return result

    @property
    def course_key(self):
        """The course key associated with the example certificate. """
        return self.example_cert_set.course_key


class CertificateGenerationCourseSetting(TimeStampedModel):
    """Enable or disable certificate generation for a particular course.

    This controls whether students are allowed to "self-generate"
    certificates for a course.  It does NOT prevent us from
    batch-generating certificates for a course using management
    commands.

    In general, we should only enable self-generated certificates
    for a course once we successfully generate example certificates
    for the course.  This is enforced in the UI layer, but
    not in the data layer.

    """
    course_key = CourseKeyField(max_length=255, db_index=True)
    enabled = models.BooleanField(default=False)

    class Meta:  # pylint: disable=missing-docstring, old-style-class
        get_latest_by = 'created'

    @classmethod
    def is_enabled_for_course(cls, course_key):
        """Check whether self-generated certificates are enabled for a course.

        Arguments:
            course_key (CourseKey): The identifier for the course.

        Returns:
            boolean

        """
        try:
            latest = cls.objects.filter(course_key=course_key).latest()
        except cls.DoesNotExist:
            return False
        else:
            return latest.enabled

    @classmethod
    def set_enabled_for_course(cls, course_key, is_enabled):
        """Enable or disable self-generated certificates for a course.

        Arguments:
            course_key (CourseKey): The identifier for the course.
            is_enabled (boolean): Whether to enable or disable self-generated certificates.

        """
        CertificateGenerationCourseSetting.objects.create(
            course_key=course_key,
            enabled=is_enabled
        )


class CertificateGenerationConfiguration(ConfigurationModel):
    """Configure certificate generation.

    Enable or disable the self-generated certificates feature.
    When this flag is disabled, the "generate certificate" button
    will be hidden on the progress page.

    When the feature is enabled, the "generate certificate" button
    will appear for courses that have enabled self-generated
    certificates.

    """
    pass
