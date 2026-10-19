import 'package:flutter/foundation.dart';

/// A student/staff's own in-app ticket notification, mirroring the
/// backend's NotificationSchema exactly (see
/// backend/app/services/ticket_notifications.py). Shared between
/// MyTicketsPage's existing unread banner and StudentMailboxPage's full
/// inbox -- both read the same `GET /tickets/notifications` response,
/// so this is reused rather than duplicated.
///
/// Privacy is enforced server-side, not here: `list_notifications` only
/// ever returns rows for the caller's own `user_id`, and a student's
/// "ticket_reply" notification is only ever created for a non-internal
/// reply (see `notify_ticket_owner` call sites in ticketing.py) -- an
/// office's internal note can never produce one of these rows for a
/// student in the first place.
class TicketNotification {
  final String id;
  final String? ticketId;
  final String type;
  final String title;
  final String body;
  final bool isRead;
  final String createdAt;

  const TicketNotification({
    required this.id,
    required this.ticketId,
    required this.type,
    required this.title,
    required this.body,
    required this.isRead,
    required this.createdAt,
  });

  factory TicketNotification.fromJson(Map<String, dynamic> json) {
    return TicketNotification(
      id: (json['id'] ?? '').toString(),
      ticketId: json['ticket_id']?.toString(),
      type: (json['type'] ?? '').toString(),
      title: (json['title'] ?? 'Update').toString(),
      body: (json['body'] ?? '').toString(),
      isRead: json['is_read'] == true,
      createdAt: (json['created_at'] ?? '').toString(),
    );
  }
}

/// Bumped whenever something outside MyTicketsPage's own fetch cycle --
/// currently: StudentMailboxPage marking one or all of the caller's own
/// notifications read -- changes that read state server-side.
/// MyTicketsPage fetches this same data independently (its own unread
/// banner/count), and its periodic 8-second poll would eventually catch
/// up on its own, but a bump here lets it refresh immediately instead of
/// showing a stale count for up to that long. Mirrors the office side's
/// `transferBadgeRefreshTick` / `TransferBadge` convention in
/// sidebar.dart for the exact same reason, scoped to the general ticket
/// notification feed instead of the transfer-specific one.
final ValueNotifier<int> ticketNotificationRefreshTick = ValueNotifier<int>(0);

/// Test-only: incremented every time MyTicketsPage's refresh-tick listener
/// actually runs (regardless of whether the subsequent fetch succeeds or
/// fails) -- there is no HTTP-mocking seam in this codebase's widget
/// tests, so this is the only way to deterministically observe "the
/// listener fired" without a real backend. Never read by production code.
@visibleForTesting
int debugTicketNotificationRefreshAttempts = 0;

/// Bumps the counter above. `@visibleForTesting` only exempts this file
/// and test code from the "don't touch this" analyzer check, but the
/// listener that needs to bump it lives in MyTicketsPage's own library --
/// this unrestricted wrapper is the one production call site allowed to
/// reach across that boundary, so the counter itself stays otherwise
/// untouchable from outside here.
void registerTicketNotificationRefreshAttempt() {
  debugTicketNotificationRefreshAttempts++;
}
