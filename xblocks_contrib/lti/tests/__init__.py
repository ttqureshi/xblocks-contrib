from opaque_keys.edx.keys import CourseKey


def get_test_system(
    course_id=CourseKey.from_string('/'.join(['org', 'course', 'run'])),
    user=None,
    user_is_staff=False,
    user_location=None,
    render_template=None,
    add_get_block_overrides=False
):
    """
    Construct a test DescriptorSystem instance.

    By default, the descriptor system's render_template() method simply returns the repr of the
    context it is passed.  You can override this by passing in a different render_template argument.
    """

    id_manager = CourseLocationManager(course_id)

    descriptor_system = get_test_descriptor_system(id_reader=id_manager, id_generator=id_manager)

    if not user:
        user = Mock(name='get_test_system.user', is_staff=False)
    if not user_location:
        user_location = Mock(name='get_test_system.user_location')
    user_service = StubUserService(
        user=user,
        anonymous_user_id='student',
        deprecated_anonymous_user_id='student',
        user_is_staff=user_is_staff,
        user_role='student',
        request_country_code=user_location,
    )

    mako_service = StubMakoService(render_template=render_template)

    replace_url_service = StubReplaceURLService()

    def get_block(block):
        """Mocks module_system get_block function"""

        prepare_block_runtime(block.runtime, add_overrides=add_get_block_overrides)
        block.runtime.get_block_for_descriptor = get_block
        block.bind_for_student(user.id)

        return block

    services = {
        'user': user_service,
        'mako': mako_service,
        'replace_urls': replace_url_service,
        'cache': CacheService(DoNothingCache()),
        'field-data': DictFieldData({}),
        'sandbox': SandboxService(contentstore, course_id),
    }

    descriptor_system.get_block_for_descriptor = get_block  # lint-amnesty, pylint: disable=attribute-defined-outside-init
    descriptor_system._services.update(services)  # lint-amnesty, pylint: disable=protected-access

    return descriptor_system