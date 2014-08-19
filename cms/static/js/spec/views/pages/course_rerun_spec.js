define(["jquery", "js/spec_helpers/create_sinon", "js/spec_helpers/view_helpers", "js/views/course_rerun",
        "js/views/utils/create_course_utils"],
    function ($, create_sinon, view_helpers, CourseRerunUtils, CreateCourseUtilsFactory) {
        describe("Create course rerun page", function () {
            var selectors = {
                    org: '.rerun-course-org',
                    number: '.rerun-course-number',
                    run: '.rerun-course-run',
                    name: '.rerun-course-name',
                    tipError: 'span.tip-error',
                    save: '.rerun-course-save',
                    cancel: '.rerun-course-cancel',
                    errorWrapper: '.wrapper-error',
                    errorMessage: '#course_rerun_error',
                    error: '.error',
                    allowUnicode: '.allow-unicode-course-id'
                },
                classes = {
                    shown: 'is-shown',
                    showing: 'is-showing',
                    hiding: 'is-hidden',
                    hidden: 'is-hidden',
                    error: 'error',
                    disabled: 'is-disabled',
                    processing: 'is-processing'
                },
                mockCreateCourseRerunHTML = readFixtures('mock/mock-create-course-rerun.underscore');

            var CreateCourseUtils = CreateCourseUtilsFactory(selectors, classes);

            var fillInFields = function (org, number, run, name) {
                $(selectors.org).val(org);
                $(selectors.number).val(number);
                $(selectors.run).val(run);
                $(selectors.name).val(name);
            };

            beforeEach(function () {
                view_helpers.installMockAnalytics();
                window.source_course_key = 'test_course_key';
                appendSetFixtures(mockCreateCourseRerunHTML);
                CourseRerunUtils.onReady();
            });

            afterEach(function () {
                view_helpers.removeMockAnalytics();
                delete window.source_course_key;
            });

            describe("Field validation", function () {
                it("returns a message for an empty string", function () {
                    var message = CreateCourseUtils.validateRequiredField('');
                    expect(message).not.toBe('');
                });

                it("does not return a message for a non empty string", function () {
                    var message = CreateCourseUtils.validateRequiredField('edX');
                    expect(message).toBe('');
                });
            });

            describe("Error messages", function () {
                var setErrorMessage = function(selector, message) {
                    var element = $(selector).parent();
                    CreateCourseUtils.setNewCourseFieldInErr(element, message);
                    return element;
                };

                it("shows an error message", function () {
                    var element = setErrorMessage(selectors.org, 'error message');
                    expect(element).toHaveClass(classes.error);
                    expect(element.children(selectors.tipError)).not.toHaveClass(classes.hidden);
                    expect(element.children(selectors.tipError)).toContainText('error message');
                });

                it("hides an error message", function () {
                    var element = setErrorMessage(selectors.org, '');
                    expect(element).not.toHaveClass(classes.error);
                    expect(element.children(selectors.tipError)).toHaveClass(classes.hidden);
                });

                it("disables the save button", function () {
                    setErrorMessage(selectors.org, 'error message');
                    expect($(selectors.save)).toHaveClass(classes.disabled);
                });

                it("enables the save button when all errors are removed", function () {
                    setErrorMessage(selectors.org, 'error message 1');
                    setErrorMessage(selectors.number, 'error message 2');
                    expect($(selectors.save)).toHaveClass(classes.disabled);
                    setErrorMessage(selectors.org, '');
                    setErrorMessage(selectors.number, '');
                    expect($(selectors.save)).not.toHaveClass(classes.disabled);
                });

                it("does not enable the save button when errors remain", function () {
                    setErrorMessage(selectors.org, 'error message 1');
                    setErrorMessage(selectors.number, 'error message 2');
                    expect($(selectors.save)).toHaveClass(classes.disabled);
                    setErrorMessage(selectors.org, '');
                    expect($(selectors.save)).toHaveClass(classes.disabled);
                });
            });

            it("saves course reruns", function () {
                var requests = create_sinon.requests(this);
                window.source_course_key = 'test_course_key';
                fillInFields('DemoX', 'DM101', '2014', 'Demo course');
                $(selectors.save).click();
                create_sinon.expectJsonRequest(requests, 'POST', '/course/', {
                    source_course_key: 'test_course_key',
                    org: 'DemoX',
                    number: 'DM101',
                    run: '2014',
                    display_name: 'Demo course'
                });
                expect($(selectors.save)).toHaveClass(classes.disabled);
                expect($(selectors.save)).toHaveClass(classes.processing);
                expect($(selectors.cancel)).toHaveClass(classes.hidden);
            });

            it("displays an error when saving fails", function () {
                var requests = create_sinon.requests(this);
                fillInFields('DemoX', 'DM101', '2014', 'Demo course');
                $(selectors.save).click();
                create_sinon.respondWithJson(requests, {
                    ErrMsg: 'error message'
                });
                expect($(selectors.errorWrapper)).not.toHaveClass(classes.hidden);
                expect($(selectors.errorWrapper)).toContainText('error message');
                expect($(selectors.save)).not.toHaveClass(classes.processing);
                expect($(selectors.cancel)).not.toHaveClass(classes.hidden);
            });

            it("does not save if there are validation errors", function () {
                var requests = create_sinon.requests(this);
                fillInFields('DemoX', 'DM101', '', 'Demo course');
                $(selectors.save).click();
                expect(requests.length).toBe(0);
            });
        });
    });
