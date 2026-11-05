/* Narrow score bridge: fixed track/parameter, pointer-sized EventInstance.
 * CMD10 text carries five resolved export names; no shared layout changes. */
static int warp_score_type(const void *type, const char *expected)
{
    char *name;
    int ok;
    if (!type) return 0;
    name = g_ic.type_get_name(type);
    ok = name && !strcmp(name, expected);
    if (name) g_ic.free_mem(name);
    return ok;
}
static int warp_cmd_audio_score(const char *text)
{
    const char *path = "event:/BGM/Battle/Battle_Cp9_Boss_10";
    char payload[WARP_CMD_TEXT_LEN];
    char *names[5], *sep, *cursor;
    int preflight, i, rc = WARP_CMD_RES_FAIL;
    HMODULE ga = GetModuleHandleW(L"GameAssembly.dll"), fmod;
    int (*valid)(uintptr_t);
    int (*release_event)(uintptr_t);
    int (*parameter)(uintptr_t, const char *, float, int);
    const void *(*field_type)(void *);
    uint32_t (*field_flags)(void *);
    void *(*class_from_type)(const void *);
    int32_t (*value_size)(void *, uint32_t *);
    uint32_t (*method_flags)(void *, uint32_t *);
    FARPROC api[5];
    uintptr_t event = 0;
    void *klass, *field, *event_class;
    const void *event_type;
    uint32_t unused = 0;
    if (!ga || !text || strlen(text) >= sizeof(payload) ||
        !g_ic.type_get_name || !g_ic.free_mem || !g_ic.method_get_return_type ||
        !g_ic.method_get_param || !g_ic.method_get_param_count ||
        !g_ic.class_get_field_from_name || !g_ic.field_static_get_value ||
        !g_ic.string_new) return WARP_CMD_RES_FAIL;
    strcpy(payload, text);
    sep = strchr(payload, '|');
    if (!sep) return WARP_CMD_RES_FAIL;
    *sep = 0; cursor = sep + 1;
    preflight = !strncmp(payload, "preflight:", 10);
    if ((!preflight && strncmp(payload, "current:", 8)) ||
        strcmp(payload + (preflight ? 10 : 8), path)) return WARP_CMD_RES_FAIL;
    for (i = 0; i < 5; ++i) {
        char *p;
        names[i] = cursor;
        sep = strchr(cursor, '|');
        if ((i < 4 && !sep) || (i == 4 && sep)) return WARP_CMD_RES_FAIL;
        if (sep) { *sep = 0; cursor = sep + 1; }
        if (!*names[i]) return WARP_CMD_RES_FAIL;
        for (p = names[i]; *p; ++p)
            if (!((*p >= 'A' && *p <= 'Z') || (*p >= 'a' && *p <= 'z') ||
                  (*p >= '0' && *p <= '9') || *p == '_')) return WARP_CMD_RES_FAIL;
        api[i] = GetProcAddress(ga, names[i]);
        if (!api[i]) return WARP_CMD_RES_FAIL;
    }
    field_type = (void *)api[0]; field_flags = (void *)api[1];
    class_from_type = (void *)api[2]; value_size = (void *)api[3];
    method_flags = (void *)api[4];
    fmod = GetModuleHandleW(L"fmodstudio.dll");
    if (!fmod) return WARP_CMD_RES_FAIL;
    valid = (void *)GetProcAddress(fmod, "FMOD_Studio_EventInstance_IsValid");
    release_event = (void *)GetProcAddress(fmod, "FMOD_Studio_EventInstance_Release");
    parameter = (void *)GetProcAddress(fmod, "FMOD_Studio_EventInstance_SetParameterByName");
    if (!valid || !release_event || !parameter) return WARP_CMD_RES_FAIL;
    klass = warp_find_class(g_domain, "BattleSoundGenerator");
    if (!klass) return WARP_CMD_RES_NO_CLASS;
    field = g_ic.class_get_field_from_name(klass, "_currentInstance");
    if (!field) return WARP_CMD_RES_NO_FIELD;
    event_type = field_type(field);
    if (!warp_score_type(event_type, "FMOD.Studio.EventInstance") ||
        !(field_flags(field) & 0x10)) return WARP_CMD_RES_FAIL;
    event_class = class_from_type(event_type);
    if (!event_class || value_size(event_class, &unused) != sizeof(event))
        return WARP_CMD_RES_FAIL;
    if (preflight) {
        void *method, *sound, *str, *result, *exc = NULL;
        void *args[2];
        klass = warp_find_class(g_domain, "SoundManager");
        if (!klass) return WARP_CMD_RES_NO_CLASS;
        method = warp_find_method_typed(klass, "TryCreateInstance", 2,
                                       "S,FMOD.Studio.EventInstance&");
        if (!method || g_ic.method_get_param_count(method) != 2 ||
            !warp_score_type(g_ic.method_get_param(method, 0), "System.String") ||
            !warp_score_type(g_ic.method_get_param(method, 1), "FMOD.Studio.EventInstance&") ||
            !warp_score_type(g_ic.method_get_return_type(method), "System.Boolean") ||
            (method_flags(method, &unused) & 0x10)) return WARP_CMD_RES_NO_METHOD;
        rc = warp_cmd_static("SoundManager::_instance", 26);
        if (rc) return rc;
        sound = warp_slot_get(26);
        if (!sound) { warp_cmd_release(26); return WARP_CMD_RES_FAIL; }
        str = g_ic.string_new(path);
        if (!str) { warp_cmd_release(26); return WARP_CMD_RES_FAIL; }
        args[0] = str; args[1] = &event;
        result = warp_safe_invoke(method, sound, args, &exc);
        warp_cmd_release(26);
        if (!exc && result && *(unsigned char *)((char *)result + 16) &&
            event && valid(event))
            rc = parameter(event, "Ryoshu", 1.0f, 1) == 0 ? 0 : WARP_CMD_RES_FAIL;
        else rc = WARP_CMD_RES_FAIL;
        if (event && release_event(event) != 0) rc = WARP_CMD_RES_FAIL;
    } else {
        g_ic.field_static_get_value(field, &event);
        rc = event && valid(event) && parameter(event, "Ryoshu", 1.0f, 1) == 0
             ? 0 : WARP_CMD_RES_FAIL;
    }
    warp_log(preflight ? "score preflight Ryoshu=1" : "score current Ryoshu=1", rc);
    return rc;
}