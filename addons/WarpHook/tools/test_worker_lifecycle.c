/* Standalone Win32 regression; no GameAssembly, injection or production DLL. */
#include <assert.h>
#include <stdio.h>
#include "../src/warp_cmd.c"

static volatile LONG attaches, detaches, active, calls;
static int fail_attach, fault_command;
static int domain_token, thread_token, object_token;
static void *fake_attach(void *domain)
{
    assert(domain == &domain_token);
    InterlockedIncrement(&attaches);
    if (fail_attach) return NULL;
    assert(InterlockedIncrement(&active) == 1);
    return &thread_token;
}
static void fake_detach(void *thread)
{
    assert(thread == &thread_token);
    assert(InterlockedDecrement(&active) == 0);
    InterlockedIncrement(&detaches);
}
static void *fake_string(const char *text)
{
    (void)text;
    assert(active == 1);
    InterlockedIncrement(&calls);
    if (fault_command) RaiseException(EXCEPTION_ACCESS_VIOLATION, 0, 0, NULL);
    return &object_token;
}
static void command(int seq, int expected)
{
    ULONGLONG deadline = GetTickCount64() + 3000;
    g_hdr->cmd_ack = 0;
    assert(work_submit(seq, WARP_CMD_PACK(WARP_CMD_STR, 0, 0, 24), 0) == 0);
    while (g_hdr->cmd_ack != seq && GetTickCount64() < deadline) Sleep(1);
    assert(g_hdr->cmd_ack == seq);
    assert(g_hdr->cmd_result == expected);
    assert(active == 0); /* detached before publishing completion */
}
int main(void)
{
    g_hdr = (WARP_HEADER *)calloc(1, WARP_MAP_BYTES);
    assert(g_hdr);
    g_domain = &domain_token;
    g_ic.thread_attach = fake_attach;
    g_ic.thread_detach = fake_detach;
    g_ic.string_new = fake_string;
    warp_work_start();
    assert(s_work_thread);
    assert(attaches == 0 && detaches == 0); /* no startup attach */
    command(1, WARP_CMD_RES_OK);
    assert(attaches == 1 && detaches == 1 && calls == 1);
    fault_command = 1;
    command(2, WARP_CMD_RES_FAIL);
    assert(attaches == 2 && detaches == 2 && calls == 2);
    fault_command = 0;
    command(3, WARP_CMD_RES_OK); /* recovered worker remains usable */
    g_ic.thread_detach = NULL;
    command(4, WARP_CMD_RES_FAIL);
    assert(attaches == 3 && detaches == 3 && calls == 3);
    g_ic.thread_detach = fake_detach;
    fail_attach = 1;
    command(5, WARP_CMD_RES_FAIL);
    assert(attaches == 4 && detaches == 3 && calls == 3);
    warp_work_stop();
    assert(!s_work_thread && !s_work_ev && !s_veh && !s_work_cs_ready);
    free(g_hdr);
    g_hdr = NULL;
    puts("PASS worker lifecycle: idle, success, AV recovery, missing detach, attach failure, stop");
    return 0;
}
