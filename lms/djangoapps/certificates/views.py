"""URL handlers related to certificate handling by LMS"""
from datetime import datetime
import dogstats_wrapper as dog_stats_api
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from capa.xqueue_interface import XQUEUE_METRIC_NAME
from certificates.models import (
    certificate_status_for_student,
    CertificateStatuses,
    GeneratedCertificate,
    CertificateHtmlViewConfiguration
)
from certificates.queue import XQueueCertInterface
from edxmako.shortcuts import render_to_response
from xmodule.course_module import CourseDescriptor
from xmodule.modulestore.django import modulestore
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from opaque_keys.edx.locations import SlashSeparatedCourseKey

logger = logging.getLogger(__name__)


@csrf_exempt
def request_certificate(request):
    """Request the on-demand creation of a certificate for some user, course.

    A request doesn't imply a guarantee that such a creation will take place.
    We intentionally use the same machinery as is used for doing certification
    at the end of a course run, so that we can be sure users get graded and
    then if and only if they pass, do they get a certificate issued.
    """
    if request.method == "POST":
        if request.user.is_authenticated():
            xqci = XQueueCertInterface()
            username = request.user.username
            student = User.objects.get(username=username)
            course_key = SlashSeparatedCourseKey.from_deprecated_string(request.POST.get('course_id'))
            course = modulestore().get_course(course_key, depth=2)

            status = certificate_status_for_student(student, course_key)['status']
            if status in [CertificateStatuses.unavailable, CertificateStatuses.notpassing, CertificateStatuses.error]:
                log_msg = u'Grading and certification requested for user %s in course %s via /request_certificate call'
                logger.info(log_msg, username, course_key)
                status = xqci.add_cert(student, course_key, course=course)
            return HttpResponse(json.dumps({'add_status': status}), mimetype='application/json')
        return HttpResponse(json.dumps({'add_status': 'ERRORANONYMOUSUSER'}), mimetype='application/json')


@csrf_exempt
def update_certificate(request):
    """
    Will update GeneratedCertificate for a new certificate or
    modify an existing certificate entry.

    See models.py for a state diagram of certificate states

    This view should only ever be accessed by the xqueue server
    """

    status = CertificateStatuses
    if request.method == "POST":

        xqueue_body = json.loads(request.POST.get('xqueue_body'))
        xqueue_header = json.loads(request.POST.get('xqueue_header'))

        try:
            course_key = SlashSeparatedCourseKey.from_deprecated_string(xqueue_body['course_id'])

            cert = GeneratedCertificate.objects.get(
                user__username=xqueue_body['username'],
                course_id=course_key,
                key=xqueue_header['lms_key'])

        except GeneratedCertificate.DoesNotExist:
            logger.critical('Unable to lookup certificate\n'
                            'xqueue_body: {0}\n'
                            'xqueue_header: {1}'.format(
                                xqueue_body, xqueue_header))

            return HttpResponse(json.dumps({
                'return_code': 1,
                'content': 'unable to lookup key'}),
                mimetype='application/json')

        if 'error' in xqueue_body:
            cert.status = status.error
            if 'error_reason' in xqueue_body:

                # Hopefully we will record a meaningful error
                # here if something bad happened during the
                # certificate generation process
                #
                # example:
                #  (aamorm BerkeleyX/CS169.1x/2012_Fall)
                #  <class 'simples3.bucket.S3Error'>:
                #  HTTP error (reason=error(32, 'Broken pipe'), filename=None) :
                #  certificate_agent.py:175

                cert.error_reason = xqueue_body['error_reason']
        else:
            if cert.status in [status.generating, status.regenerating]:
                cert.download_uuid = xqueue_body['download_uuid']
                cert.verify_uuid = xqueue_body['verify_uuid']
                cert.download_url = xqueue_body['url']
                cert.status = status.downloadable
            elif cert.status in [status.deleting]:
                cert.status = status.deleted
            else:
                logger.critical('Invalid state for cert update: {0}'.format(
                    cert.status))
                return HttpResponse(
                    json.dumps({
                        'return_code': 1,
                        'content': 'invalid cert status'
                    }),
                    mimetype='application/json'
                )

        dog_stats_api.increment(XQUEUE_METRIC_NAME, tags=[
            u'action:update_certificate',
            u'course_id:{}'.format(cert.course_id)
        ])

        cert.save()
        return HttpResponse(json.dumps({'return_code': 0}),
                            mimetype='application/json')


@login_required
def render_html_view(request):
    """
    This view generates an HTML representation of the specified student's certificate
    If a certificate is not available, we display a "Sorry!" screen instead
    """
    invalid_template_path = 'certificates/invalid.html'

    # Feature Flag check
    if not settings.FEATURES.get('CERTIFICATES_HTML_VIEW', False):
        return render_to_response(invalid_template_path)

    context = {}
    course_id = request.GET.get('course', None)
    context['course'] = course_id
    if not course_id:
        return render_to_response(invalid_template_path, context)

    # Course Lookup
    try:
        course_key = CourseKey.from_string(course_id)
    except InvalidKeyError:
        return render_to_response(invalid_template_path, context)
    course = modulestore().get_course(course_key)
    if not course:
        return render_to_response(invalid_template_path, context)

    # Certificate Lookup
    try:
        certificate = GeneratedCertificate.objects.get(
            user=request.user,
            course_id=course_key
        )
    except GeneratedCertificate.DoesNotExist:
        return render_to_response(invalid_template_path, context)

    # Load static output values from configuration,
    configuration = CertificateHtmlViewConfiguration.get_config()
    context = configuration.get('default', {})
    # Override the defaults with any mode-specific static values
    context.update(configuration.get(certificate.mode, {}))
    # Override further with any course-specific static values
    context.update(course.cert_html_view_overrides)


    # Populate dynamic output values using the course/certificate data loaded above
    user_fullname = request.user.profile.name
    company_name = context.get('company_name')
    context['accomplishment_copy_name'] = user_fullname
    accd = 'a course of study offered by <span class="detail--xuniversity">{0}</span>'.format(course.org)
    accd = accd + ', through <span class="detail--company">{0}</span>.'.format(company_name)
    context['accomplishment_copy_course_description'] = accd
    context['accomplishment_copy_course_org'] = course.org
    context['accomplishment_copy_course_name'] = course.display_name
    context['accomplishment_more_title'] = "More Information About {0}'s Certificate:".format(user_fullname)
    context['certificate_date_issued'] = certificate.modified_date.strftime("%B %m, %Y")
    context['certificate_id_number'] = certificate.verify_uuid
    context['certificate_verify_url'] = "{0}{1}{2}".format(
        context.get('certificate_verify_url_prefix'),
        certificate.verify_uuid,
        context.get('certificate_verify_url_suffix')
    )
    context['copyright_text'] = "&copy; {0} {1}. All rights reserved".format(datetime.now().year, company_name)
    dmd = "This is a valid {0} certificate for {1}, ".format(company_name, user_fullname)
    dmd = dmd + "who participated in {0} {1}".format(course.org, course.number).format()
    context['document_meta_description'] = dmd
    context['document_title'] = "Valid {} {} Certificate | {}".format(course.org, course.number, company_name)
    context['accomplishment_copy_description_full'] = '{}{}'.format(
        context.get('accomplishment_copy_description'),
        context.get('accomplishment_copy_description_suffix')
    )
    return render_to_response("certificates/valid.html", context)
