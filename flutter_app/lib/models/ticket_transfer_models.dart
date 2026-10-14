/// Office-to-office ticket transfer request, mirroring the backend's
/// TicketTransferRequestSchema exactly. Deliberately carries only transfer
/// metadata (office ids/names, reason, status, decision info) -- never
/// ticket conversation, attachments, or internal-note content, since the
/// backend schema itself never includes those fields.
class TicketTransferRequest {
  const TicketTransferRequest({
    required this.id,
    required this.ticketId,
    required this.sourceOfficeId,
    required this.sourceOfficeName,
    required this.destinationOfficeId,
    required this.destinationOfficeName,
    required this.initiatedByUserId,
    required this.reason,
    required this.status,
    required this.createdAt,
    this.decidedAt,
    this.decidedByUserId,
    this.rejectionReason,
  });

  final String id;
  final String ticketId;
  final String sourceOfficeId;
  final String sourceOfficeName;
  final String destinationOfficeId;
  final String destinationOfficeName;
  final String initiatedByUserId;
  final String reason;
  final String status;
  final String createdAt;
  final String? decidedAt;
  final String? decidedByUserId;
  final String? rejectionReason;

  bool get isPending => status == 'Pending';
  bool get isAccepted => status == 'Accepted';
  bool get isRejected => status == 'Rejected';

  factory TicketTransferRequest.fromJson(Map<String, dynamic> json) {
    return TicketTransferRequest(
      id: (json['id'] ?? '').toString(),
      ticketId: (json['ticket_id'] ?? '').toString(),
      sourceOfficeId: (json['source_office_id'] ?? '').toString(),
      sourceOfficeName: (json['source_office_name'] ?? '').toString(),
      destinationOfficeId: (json['destination_office_id'] ?? '').toString(),
      destinationOfficeName:
          (json['destination_office_name'] ?? '').toString(),
      initiatedByUserId: (json['initiated_by_user_id'] ?? '').toString(),
      reason: (json['reason'] ?? '').toString(),
      status: (json['status'] ?? 'Pending').toString(),
      createdAt: (json['created_at'] ?? '').toString(),
      decidedAt: json['decided_at']?.toString(),
      decidedByUserId: json['decided_by_user_id']?.toString(),
      rejectionReason: json['rejection_reason']?.toString(),
    );
  }
}

/// Notification `type` values that are exclusive to the transfer workflow
/// (confirmed by grepping the backend: none of these three strings are
/// used by any other notification path). "ticket_assigned" and
/// "office_reassigned" are deliberately excluded -- both are shared with
/// the plain admin-reassignment path, so counting them would conflate
/// unrelated activity with transfer-specific unread notifications.
const transferNotificationTypes = <String>{
  'transfer_requested',
  'transfer_accepted',
  'transfer_rejected',
};

/// Counts unread notifications whose `type` is transfer-specific, given a
/// decoded notification list. Kept as a standalone, independently-tested
/// utility -- the live sidebar badge no longer uses this, since
/// `GET /tickets/notifications?unread_only=true` is capped server-side at
/// the 100 most recent notifications and can silently exclude older unread
/// transfer ones once a user's total unread backlog exceeds that cap. The
/// badge instead calls the dedicated, un-paginated
/// `GET /tickets/notifications/transfers/unread-count` endpoint.
int countUnreadTransferNotifications(List<dynamic> items) {
  var count = 0;
  for (final item in items) {
    if (item is! Map) continue;
    final isRead = item['is_read'] == true;
    final type = (item['type'] ?? '').toString();
    if (!isRead && transferNotificationTypes.contains(type)) {
      count++;
    }
  }
  return count;
}
