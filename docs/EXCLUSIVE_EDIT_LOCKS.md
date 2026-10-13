# Exclusive KiCad project editing locks — TAUV Client 2.2.0

This feature is server-enforced. Deploy the matching backend before allowing
team users to upgrade. A healthy tunnel or client EXE alone is insufficient.

## Workflow

1. Designer/Admin selects a shared project and clicks **Open in KiCad**.
2. The Windows client atomically acquires a 180-second exclusive lease on the
   TAUVSYNC backend. The server responds with a secret token for that session.
3. All other users see **Locked: owner**. They may inspect thumbnails and
   download historical revisions, but cannot open the shared editing copy.
4. TAUV renews the lease every 30 seconds while its window is open/minimized.
5. The backend rejects **ALL** revision writes/restores without a valid lease
   token owned by the authenticated editing session, including older clients.
6. Close KiCad editors and synchronize changes, then click **Release lock**.
   Normal TAUV exit/sign-out also releases leases, once editors are closed.
7. Crashed/offline sessions expire after 180 seconds. Admin-only
   `DELETE /api/tauvsync/projects/{id}/edit-lock/force` releases abandoned
   locks immediately. Releasing invalidates all previous session tokens.

Lock metadata includes the owner and expiry, never the token. Tokens are stored
only in client memory and are not written to the managed checkout, preferences,
logs or repository.

## Safety limitations

- This is a **project-wide** lock, not a per-file lock.
- Users with local copies can still modify files offline or outside TAUV;
  the server blocks publishing without the exclusive lease.
- TAUV must remain running/minimized to renew ownership. Force-killing TAUV
  or disconnecting it eventually releases the lock by expiration, even if
  a KiCad editor remains open. Users must close editors before quitting.
- Other server endpoints/tools which directly modify Prism's underlying Git
  working directory are not governed by this API unless separately restricted.
- Immutable historical revisions remain available for download and recovery.
