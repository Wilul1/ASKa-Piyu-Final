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
