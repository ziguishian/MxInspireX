from app.image_intent import derive_image_intents, validate_reference_modes, ReferenceModeMismatchError


def intent(message, ids=('image-a',), **context):
    return derive_image_intents({'userMessage': message, **context}, list(ids))


def test_specific_image_scene_and_object_changes_are_edits_but_generation_verbs_are_neutral():
    result = intent('@asset:image-a 生成这张图中这条船在夜晚的场景，然后船上要有人。画面的比例为16:9')
    assert result[0]['expectedOperation'] == 'edit'
    assert result[0]['expectedMode'] == 'edit'
    assert any('夜晚' in evidence or '要有人' in evidence for evidence in result[0]['evidence'])
    assert intent('生成一张16:9的夜晚游船概念图')[0]['expectedOperation'] == 'ambiguous'


def test_common_single_image_changes_are_edits():
    for message in ('删除人物', '换背景为海边', '把文字改成欢迎光临', '把杯子改为红色'):
        assert intent(message)[0]['expectedOperation'] == 'edit', message


def test_reference_language_and_no_edit_constraint_win():
    for message in ('参考这张图的配色', '制作类似风格的另一款设计', '借鉴画面氛围'):
        assert intent(message)[0]['expectedOperation'] == 'reference', message
    result = intent('不要修改原图，只参考风格；生成另一款方案')
    assert result[0]['expectedOperation'] == 'reference'
    assert result[0]['expectedMode'] == 'inspiration'


def test_multiple_named_images_get_independent_roles():
    context = {'referencedAssets': [
        {'id': 'base', 'mention': '@asset:base'},
        {'id': 'logo', 'mention': '@asset:logo'},
        {'id': 'style', 'mention': '@asset:style'},
    ]}
    result = intent('@asset:base 换成夜晚并增加人物，@asset:logo 保持Logo身份和形状，@asset:style 只参考风格',
                    ('base', 'logo', 'style'), **context)
    assert [(item['assetId'], item['expectedMode']) for item in result] == [
        ('base', 'edit'), ('logo', 'identity'), ('style', 'inspiration')]


def test_unnamed_multi_image_pronouns_do_not_force_every_image_to_edit():
    result = intent(
        '参考图中的极简背景，把这张图改成米白色并加一点淡蓝色',
        ('target', 'style'),
        referencedAssets=[{'id':'target'}, {'id':'style'}],
    )
    assert [(item['expectedOperation'], item['confidence']) for item in result] == [
        ('ambiguous', 'low'), ('ambiguous', 'low')]
    # The Agent may now express the meaningful per-image combination without a
    # false-positive mismatch from the user's unresolved singular pronoun.
    validate_reference_modes(result, {'images': [
        {'asset_id':'target', 'mode':'edit'},
        {'asset_id':'style', 'mode':'inspiration'},
    ]})


def test_multi_image_indices_bind_roles_and_collective_edits_apply_to_all():
    context = {'referencedAssets': [{'id':'target'}, {'id':'style'}]}
    result = intent('图1改成米白色，图2只参考极简风格', ('target', 'style'), **context)
    assert [(item['assetId'], item['expectedMode']) for item in result] == [
        ('target', 'edit'), ('style', 'inspiration')]
    collective = intent('把这两张图都改成米白色', ('target', 'style'), **context)
    assert [item['expectedMode'] for item in collective] == ['edit', 'edit']


def test_shared_multi_asset_mention_clause_is_not_treated_as_per_image_binding():
    context = {'referencedAssets': [
        {'id':'target', 'mention':'@asset:target'},
        {'id':'style', 'mention':'@asset:style'},
    ]}
    result = intent('@asset:target @asset:style 参考极简背景，把这张图改成米白色',
                    ('target', 'style'), **context)
    assert [item['expectedOperation'] for item in result] == ['ambiguous', 'ambiguous']


def test_user_override_has_priority_and_mismatch_is_structured():
    result = intent('不要修改原图，只参考风格', canvasParams={'referenceModes': {'image-a': 'edit'}})
    assert result[0]['expectedMode'] == 'edit'
    assert result[0]['source'] == 'user_override'
    try:
        validate_reference_modes(result, {'images': [{'asset_id': 'image-a', 'mode': 'inspiration'}]})
    except ReferenceModeMismatchError as error:
        assert error.code == 'reference_mode_mismatch'
        assert error.asset_ids == ['image-a']
        assert error.details['expectedMode'] == 'edit'
        assert error.details['actualMode'] == 'inspiration'
    else:
        raise AssertionError('mismatch was not rejected')
