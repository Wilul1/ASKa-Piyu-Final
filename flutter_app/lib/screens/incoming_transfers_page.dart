import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/ticket_transfer_models.dart';
import '../services/api_client.dart';
import '../widgets/responsive_dialog_body.dart';
import '../widgets/sidebar.dart';
import 'admin_scaffold.dart';
import 'office_scaffold.dart';

/// Office/admin mailbox for office-to-office ticket transfer requests.
/// Shows only TicketTransferRequest fields (office names, reason, status,
/// decision metadata) -- never ticket conversation, attachments, or
/// internal notes, since the backend endpoints it calls never return those.
///
/// Presented as a mailbox, not a tab-based workspace: this page IS the
/// incoming list. Selecting a row opens its details (with Accept/Reject for
/// a Pending request); outgoing requests live in a separate, secondary page
/// reached via the "Outgoing requests" action, never as a sibling tab.
class IncomingTransfersPage extends StatefulWidget {
  const IncomingTransfersPage({
    super.key,
    this.debugIncoming,
    this.debugOutgoing,
  });

  /// Seeded incoming requests skip the network load. Widget tests only.
  @visibleForTesting
  final List<Map<String, dynamic>>? debugIncoming;

  /// Forwarded to the secondary Outgoing page when it's opened. Widget
  /// tests only -- lets a test seed outgoing data without that page ever
  /// being directly importable (it's private to this file).
  @visibleForTesting
  final List<Map<String, dynamic>>? debugOutgoing;

  @override
  State<IncomingTransfersPage> createState() => _IncomingTransfersPageState();
}

class _IncomingTransfersPageState extends State<IncomingTransfersPage> {
  final List<TicketTransferRequest> _incoming = [];
  bool _loadingIncoming = false;
  String? _incomingError;
  bool _requestedInitialLoad = false;
  bool _markingNotificationsRead = false;
  // Per-request-id busy set, not a single id: a decision on one request
  // must never block deciding a *different* one -- only a second decision
  // on the SAME id while its own call is still in flight.
  final Set<String> _actingOnIds = {};

  @override
  void initState() {
    super.initState();
    final incomingSeed = widget.debugIncoming;
    if (incomingSeed != null) {
      _requestedInitialLoad = true;
      _incoming.addAll(
        incomingSeed.map(
          (item) =>
              TicketTransferRequest.fromJson(Map<String, dynamic>.from(item)),
        ),
      );
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    final canLoad = auth.role == 'office' || auth.role == 'admin';
    if (!_requestedInitialLoad && canLoad) {
      _requestedInitialLoad = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        _loadIncoming();
      });
    }
  }

  Future<void> _loadIncoming() async {
    setState(() {
      _loadingIncoming = true;
      _incomingError = null;
    });
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/transfers/incoming',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      if (!result.ok) {
        throw StateError(
          _extractError(
            result.jsonObject,
            'Could not load incoming transfer requests.',
          ),
        );
      }
      final parsed = _parseTransferItems(result.jsonObject['items']);
      if (!mounted) return;
      setState(() {
        _incoming
          ..clear()
          ..addAll(parsed);
      });
    } catch (error) {
      if (mounted) setState(() => _incomingError = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loadingIncoming = false);
    }
  }

  Future<void> _decide(
    TicketTransferRequest request, {
    required bool accept,
    String? rejectionReason,
  }) async {
    // Guards only this SAME request id -- a different id already in flight
    // (or decided afterward) is untouched, so other requests stay usable.
    if (_actingOnIds.contains(request.id)) return;
    setState(() => _actingOnIds.add(request.id));
    try {
      final action = accept ? 'accept' : 'reject';
      final result = await ApiClient.send(
        method: 'POST',
        url:
            '${AppConfig.resolvedApiBase}/tickets/transfers/${request.id}/$action',
        headers: AuthScope.of(context).ticketHeaders(),
        jsonBody: accept ? null : {'rejection_reason': rejectionReason},
      );
      if (!result.ok) {
        throw StateError(
          _extractError(
            result.jsonObject,
            accept
                ? 'Could not accept transfer request.'
                : 'Could not reject transfer request.',
          ),
        );
      }
      if (!mounted) return;
      setState(() {
        _incoming.removeWhere((item) => item.id == request.id);
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(accept ? 'Transfer accepted.' : 'Transfer rejected.'),
        ),
      );
      await _loadIncoming();
      // A decision resolves the destination office's own "please decide"
      // notification server-side (see accept/reject_ticket_transfer); tell
      // the sidebar badge -- a sibling widget with no other connection to
      // this action -- to refetch so it doesn't stay stale for the rest of
      // this session.
      transferBadgeRefreshTick.value++;
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(_friendlyError(error))));
      }
    } finally {
      // Runs on every exit path -- success, the thrown-error branch above,
      // and any unexpected exception -- so this id is never left stuck as
      // permanently busy.
      if (mounted) setState(() => _actingOnIds.remove(request.id));
    }
  }

  Future<void> _markTransferNotificationsRead() async {
    // Deliberately explicit, user-initiated -- never triggered just by
    // opening or refreshing this screen. This is a bulk action, not a
    // precise per-notification one: the mailbox only has transfer-request
    // ids, not individual notification ids, so there is no safe way to
    // target "just this one outgoing notification" without adding a
    // finer-grained identifier the API doesn't expose. Marking the
    // caller's whole transfer-notification backlog read in one explicit
    // action is the safest supported alternative.
    if (_markingNotificationsRead) return;
    setState(() => _markingNotificationsRead = true);
    try {
      final result = await ApiClient.send(
        method: 'POST',
        url:
            '${AppConfig.resolvedApiBase}/tickets/notifications/transfers/read-all',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      if (!result.ok) {
        throw StateError(
          _extractError(
            result.jsonObject,
            'Could not mark notifications read.',
          ),
        );
      }
      transferBadgeRefreshTick.value++;
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Transfer notifications marked read.')),
        );
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(_friendlyError(error))));
      }
    } finally {
      if (mounted) setState(() => _markingNotificationsRead = false);
    }
  }

  Future<void> _promptReject(TicketTransferRequest request) async {
    final controller = TextEditingController();
    try {
      final confirmed = await showDialog<bool>(
        context: context,
        builder:
            (dialogContext) => AlertDialog(
              title: const Text('Reject transfer request'),
              content: TextField(
                controller: controller,
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: 'Reason (optional)',
                  border: OutlineInputBorder(),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(false),
                  child: const Text('Cancel'),
                ),
                FilledButton(
                  onPressed: () => Navigator.of(dialogContext).pop(true),
                  child: const Text('Reject'),
                ),
              ],
            ),
      );
      // confirmed is also null here if the dialog was dismissed via the
      // barrier/back button rather than Cancel/Reject -- treated the same
      // as an explicit cancel.
      if (confirmed != true || !mounted) return;
      final reason = controller.text.trim();
      await _decide(
        request,
        accept: false,
        rejectionReason: reason.isEmpty ? null : reason,
      );
    } finally {
      // Runs for every exit path -- Cancel, Reject, barrier/back-button
      // dismissal, and normal completion -- so the controller is always
      // released exactly once.
      controller.dispose();
    }
  }

  /// Opens the message's details. A Pending request's dialog returns
  /// 'accept'/'reject'; this method runs the actual decision only after
  /// that dialog has already closed, exactly mirroring how `_promptReject`
  /// already hands off from its own sub-dialog.
  Future<void> _openDetails(TicketTransferRequest request) async {
    // A decision for this id is already in flight -- the row itself is
    // disabled while that's true (see _buildBody), but this is a second,
    // defensive guard against reopening details for it by any other path.
    if (_actingOnIds.contains(request.id)) return;
    final action = await showDialog<String>(
      context: context,
      builder: (_) => _TransferDetailsDialog(request: request),
    );
    if (!mounted || action == null) return;
    if (action == 'accept') {
      await _decide(request, accept: true);
    } else if (action == 'reject') {
      await _promptReject(request);
    }
  }

  Future<void> _openOutgoing() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder:
            (_) => _OutgoingTransfersPage(debugItems: widget.debugOutgoing),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    final isOffice = auth.role == 'office';
    final body = _buildBody();
    final actions = [
      TextButton(
        onPressed: _openOutgoing,
        child: const Text('Outgoing requests'),
      ),
      TextButton(
        onPressed:
            _markingNotificationsRead ? null : _markTransferNotificationsRead,
        child: Text(
          _markingNotificationsRead ? 'Marking…' : 'Mark notifications read',
        ),
      ),
    ];

    if (isOffice) {
      return OfficeScaffold(
        current: StudentNavItem.officeIncomingTransfers,
        title: 'Incoming Transfers',
        description:
            'Review office-to-office ticket transfer requests sent to your office.',
        actions: actions,
        child: body,
      );
    }
    return AdminScaffold(
      current: StudentNavItem.adminIncomingTransfers,
      title: 'Incoming Transfers',
      description:
          'Review office-to-office ticket transfer requests sent to your office.',
      actions: actions,
      child: body,
    );
  }

  Widget _buildBody() {
    if (_loadingIncoming && _incoming.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 32),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (_incomingError != null) {
      return _ErrorBanner(message: _incomingError!, onRetry: _loadIncoming);
    }
    if (_incoming.isEmpty) {
      return const _EmptyState(message: 'No incoming transfer requests.');
    }
    return Column(
      children:
          _incoming.map((request) {
            final busy = _actingOnIds.contains(request.id);
            return _MailboxRow(
              request: request,
              busy: busy,
              onTap: busy ? null : () => _openDetails(request),
            );
          }).toList(),
    );
  }
}

/// A separate, secondary page for the caller's own outgoing transfer
/// requests -- deliberately not a tab alongside the incoming mailbox (see
/// IncomingTransfersPage's own doc comment). Self-contained: fetches its
/// own data rather than depending on IncomingTransfersPage's state, so it
/// stays correct however it's reached.
class _OutgoingTransfersPage extends StatefulWidget {
  const _OutgoingTransfersPage({this.debugItems});

  @visibleForTesting
  final List<Map<String, dynamic>>? debugItems;

  @override
  State<_OutgoingTransfersPage> createState() => _OutgoingTransfersPageState();
}

class _OutgoingTransfersPageState extends State<_OutgoingTransfersPage> {
  final List<TicketTransferRequest> _items = [];
  bool _loading = false;
  String? _error;
  bool _requestedInitialLoad = false;
  bool _markingNotificationsRead = false;

  @override
  void initState() {
    super.initState();
    final seed = widget.debugItems;
    if (seed != null) {
      _requestedInitialLoad = true;
      _items.addAll(
        seed.map(
          (item) =>
              TicketTransferRequest.fromJson(Map<String, dynamic>.from(item)),
        ),
      );
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    final canLoad = auth.role == 'office' || auth.role == 'admin';
    if (!_requestedInitialLoad && canLoad) {
      _requestedInitialLoad = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        _load();
      });
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/transfers/outgoing',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      if (!result.ok) {
        throw StateError(
          _extractError(
            result.jsonObject,
            'Could not load outgoing transfer requests.',
          ),
        );
      }
      final parsed = _parseTransferItems(result.jsonObject['items']);
      if (!mounted) return;
      setState(() {
        _items
          ..clear()
          ..addAll(parsed);
      });
    } catch (error) {
      if (mounted) setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// This is where a source office actually learns a transfer it sent was
  /// accepted/rejected -- the unread notification for that outcome
  /// (type "transfer_accepted"/"transfer_rejected", see accept_ticket_
  /// transfer/reject_ticket_transfer in ticketing.py) is addressed to the
  /// SOURCE office, never to the destination. Previously this action only
  /// existed on the Incoming page, which a pure source office may never
  /// visit (they have nothing pending to decide there) -- leaving that
  /// notification permanently unread and the sidebar badge stuck non-zero
  /// even after returning to the office workspace. Same explicit,
  /// user-initiated bulk action as Incoming's, hitting the same endpoint;
  /// never auto-triggered just by viewing this list.
  Future<void> _markTransferNotificationsRead() async {
    if (_markingNotificationsRead) return;
    setState(() => _markingNotificationsRead = true);
    try {
      final result = await ApiClient.send(
        method: 'POST',
        url:
            '${AppConfig.resolvedApiBase}/tickets/notifications/transfers/read-all',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      if (!result.ok) {
        throw StateError(
          _extractError(
            result.jsonObject,
            'Could not mark notifications read.',
          ),
        );
      }
      transferBadgeRefreshTick.value++;
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Transfer notifications marked read.')),
        );
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(_friendlyError(error))));
      }
    } finally {
      if (mounted) setState(() => _markingNotificationsRead = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    final isOffice = auth.role == 'office';
    final body = _buildBody();
    final actions = [
      TextButton(
        onPressed:
            _markingNotificationsRead ? null : _markTransferNotificationsRead,
        child: Text(
          _markingNotificationsRead ? 'Marking…' : 'Mark notifications read',
        ),
      ),
    ];
    if (isOffice) {
      return OfficeScaffold(
        current: StudentNavItem.officeIncomingTransfers,
        title: 'Outgoing Transfers',
        description: 'Transfer requests your office has sent to other offices.',
        actions: actions,
        child: body,
      );
    }
    return AdminScaffold(
      current: StudentNavItem.adminIncomingTransfers,
      title: 'Outgoing Transfers',
      description: 'Transfer requests sent to other offices.',
      actions: actions,
      child: body,
    );
  }

  Widget _buildBody() {
    if (_loading && _items.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 32),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (_error != null) {
      return _ErrorBanner(message: _error!, onRetry: _load);
    }
    if (_items.isEmpty) {
      return const _EmptyState(message: 'No outgoing transfer requests.');
    }
    return Column(
      children:
          _items
              .map(
                (request) => _TransferCard(request: request, isIncoming: false),
              )
              .toList(),
    );
  }
}

/// One mailbox-style row for the incoming list. Tapping it opens the
/// request's details (see _TransferDetailsDialog) -- Accept/Reject live
/// there, not inline on the row, so the mailbox reads as a list of
/// messages rather than a grid of action cards.
class _MailboxRow extends StatelessWidget {
  const _MailboxRow({
    required this.request,
    required this.onTap,
    this.busy = false,
  });

  final TicketTransferRequest request;

  /// Null (not just a no-op callback) while `busy` is true, so the row is
  /// genuinely un-tappable -- not just visually dimmed -- during its own
  /// in-flight accept/reject decision.
  final VoidCallback? onTap;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    // Inbox ordering: sender (source office) + timestamp on the first
    // line, the reason as a subject-style preview on the second, then a
    // small metadata line (ticket reference + status) -- the same fields
    // as before, just ordered the way a mail list reads rather than a
    // ticket-management card.
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Opacity(
          opacity: busy ? 0.6 : 1,
          child: Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              border: Border.all(color: DesignTokens.border),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              request.sourceOfficeName,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontWeight: FontWeight.w800,
                                fontSize: 14,
                                color: DesignTokens.ink,
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          // Flexible, not a bare Text: without a width
                          // budget of its own this non-expanding sibling
                          // forces a RenderFlex overflow on narrow screens
                          // regardless of how short the string is.
                          Flexible(
                            child: Text(
                              _formatRequestDateCompact(request.createdAt),
                              overflow: TextOverflow.ellipsis,
                              maxLines: 1,
                              textAlign: TextAlign.right,
                              style: const TextStyle(
                                fontSize: 11,
                                color: DesignTokens.muted,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        request.reason.isEmpty
                            ? 'No reason given.'
                            : request.reason,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 13,
                          color: DesignTokens.ink,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              'Ticket #${request.ticketId}',
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                                color: DesignTokens.muted,
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          _StatusLabel(status: request.status),
                        ],
                      ),
                    ],
                  ),
                ),
                if (busy) ...[
                  const SizedBox(width: 8),
                  const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// A message's full details, opened from _MailboxRow. Pending requests get
/// Accept/Reject; the actual decision runs only after this dialog has
/// closed (see IncomingTransfersPage._openDetails), so this widget never
/// needs its own busy/error state for the decision itself.
class _TransferDetailsDialog extends StatelessWidget {
  const _TransferDetailsDialog({required this.request});

  final TicketTransferRequest request;

  @override
  Widget build(BuildContext context) {
    // Reading-pane layout: the sender (source office) and status read like
    // an opened message's header, a divider separates header from body,
    // the reason is the message body, and the rest is footer metadata --
    // same fields as the row (ticket reference, destination, requested
    // time, rejection reason), just ordered like a message, not a form.
    return AlertDialog(
      title: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  request.sourceOfficeName,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 8),
              _StatusLabel(status: request.status),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            'Ticket #${request.ticketId} → ${request.destinationOfficeName}',
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: DesignTokens.muted,
            ),
          ),
        ],
      ),
      content: ResponsiveDialogBody(
        maxWidth: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Divider(height: 1, color: DesignTokens.border),
            const SizedBox(height: 14),
            Text(
              request.reason.isEmpty ? 'No reason given.' : request.reason,
              style: const TextStyle(fontSize: 14, color: DesignTokens.ink),
            ),
            const SizedBox(height: 14),
            Text(
              'Requested ${_formatRequestTimestamp(request.createdAt)}',
              style: const TextStyle(fontSize: 12, color: DesignTokens.muted),
            ),
            if (request.rejectionReason != null &&
                request.rejectionReason!.isNotEmpty) ...[
              const SizedBox(height: 10),
              _DetailLine(
                label: 'Rejection reason',
                value: request.rejectionReason!,
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
        if (request.isPending) ...[
          TextButton(
            onPressed: () => Navigator.of(context).pop('reject'),
            child: const Text('Reject'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop('accept'),
            child: const Text('Accept'),
          ),
        ],
      ],
    );
  }
}

class _DetailLine extends StatelessWidget {
  const _DetailLine({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w700,
            color: DesignTokens.muted,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: const TextStyle(fontSize: 14, color: DesignTokens.ink),
        ),
      ],
    );
  }
}

/// Read-only card used only by the Outgoing subpage -- the caller never
/// gets Accept/Reject on their own outgoing requests.
class _TransferCard extends StatelessWidget {
  const _TransferCard({required this.request, required this.isIncoming});

  final TicketTransferRequest request;
  final bool isIncoming;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        border: Border.all(color: DesignTokens.border),
        borderRadius: BorderRadius.circular(12),
        color: Colors.white,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  'Ticket #${request.ticketId}',
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 14,
                    color: DesignTokens.ink,
                  ),
                ),
              ),
              _StatusLabel(status: request.status),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            isIncoming
                ? 'From ${request.sourceOfficeName}'
                : 'To ${request.destinationOfficeName}',
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: DesignTokens.muted,
            ),
          ),
          if (request.reason.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              request.reason,
              style: const TextStyle(fontSize: 13, color: DesignTokens.ink),
            ),
          ],
          if (request.rejectionReason != null &&
              request.rejectionReason!.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              'Rejection reason: ${request.rejectionReason}',
              style: const TextStyle(fontSize: 12, color: DesignTokens.muted),
            ),
          ],
          const SizedBox(height: 8),
          Text(
            _formatRequestTimestamp(request.createdAt),
            style: const TextStyle(fontSize: 11, color: DesignTokens.muted),
          ),
        ],
      ),
    );
  }
}

class _StatusLabel extends StatelessWidget {
  const _StatusLabel({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      'Accepted' => const Color(0xFF1B7F3A),
      'Rejected' => const Color(0xFFB3261E),
      _ => DesignTokens.maroon,
    };
    return Text(
      status,
      style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: color),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 32),
      child: Center(
        child: Text(message, style: const TextStyle(color: DesignTokens.muted)),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFFDECEA),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              message,
              style: const TextStyle(color: Color(0xFFB3261E)),
            ),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}

/// Readable "Oct 13, 2026, 2:05 PM" form of the request's raw ISO-8601
/// `createdAt` string. Falls back to the raw string if it doesn't parse,
/// rather than showing nothing. No `intl` dependency -- mirrors the same
/// manual month-name convention this app's other screens already use
/// (see _adminFormatDate/_officeDashboardTimeLine in
/// admin_management_pages.dart), duplicated locally since that's a
/// separate library from this standalone page.
String _formatRequestTimestamp(String iso) {
  final parsed = DateTime.tryParse(iso);
  if (parsed == null) return iso;
  final local = parsed.toLocal();
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  final hour24 = local.hour;
  final hour = hour24 == 0 ? 12 : (hour24 > 12 ? hour24 - 12 : hour24);
  final minute = local.minute.toString().padLeft(2, '0');
  final meridiem = hour24 >= 12 ? 'PM' : 'AM';
  return '${months[local.month - 1]} ${local.day}, ${local.year}, $hour:$minute $meridiem';
}

/// Short "Oct 13" form for the mailbox row, which shares its line with the
/// sender name -- the full date+time form (_formatRequestTimestamp) is too
/// wide there on narrow screens. The full form is still shown once the
/// message is open (see _TransferDetailsDialog), matching how a mail
/// client's list view uses a compact date and the opened message shows
/// the full one.
String _formatRequestDateCompact(String iso) {
  final parsed = DateTime.tryParse(iso);
  if (parsed == null) return iso;
  final local = parsed.toLocal();
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  return '${months[local.month - 1]} ${local.day}';
}

List<TicketTransferRequest> _parseTransferItems(Object? rawItems) {
  if (rawItems is! List) return const [];
  return rawItems
      .whereType<Map>()
      .map(
        (item) =>
            TicketTransferRequest.fromJson(Map<String, dynamic>.from(item)),
      )
      .toList();
}

String _extractError(Map<String, dynamic> data, String fallback) {
  final detail = data['detail'];
  if (detail is String && detail.trim().isNotEmpty) return detail;
  if (detail is List && detail.isNotEmpty) {
    return detail.map((item) => item.toString()).join('\n');
  }
  return fallback;
}

String _friendlyError(Object error) {
  final message = error.toString().replaceFirst('Bad state: ', '').trim();
  return message.isEmpty
      ? 'The backend did not return a usable response.'
      : message;
}
