import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/ticket_transfer_models.dart';
import '../services/api_client.dart';
import '../widgets/sidebar.dart';
import 'admin_scaffold.dart';
import 'office_scaffold.dart';

/// Office/admin mailbox for office-to-office ticket transfer requests.
/// Shows only TicketTransferRequest fields (office names, reason, status,
/// decision metadata) -- never ticket conversation, attachments, or
/// internal notes, since the backend endpoints it calls never return those.
class IncomingTransfersPage extends StatefulWidget {
  const IncomingTransfersPage({
    super.key,
    this.debugIncoming,
    this.debugOutgoing,
  });

  /// Seeded incoming requests skip the network load. Widget tests only.
  @visibleForTesting
  final List<Map<String, dynamic>>? debugIncoming;

  /// Seeded outgoing requests skip the network load. Widget tests only.
  @visibleForTesting
  final List<Map<String, dynamic>>? debugOutgoing;

  @override
  State<IncomingTransfersPage> createState() => _IncomingTransfersPageState();
}

class _IncomingTransfersPageState extends State<IncomingTransfersPage> {
  final List<TicketTransferRequest> _incoming = [];
  final List<TicketTransferRequest> _outgoing = [];
  bool _loadingIncoming = false;
  bool _loadingOutgoing = false;
  String? _incomingError;
  String? _outgoingError;
  bool _requestedInitialLoad = false;
  int _tab = 0; // 0 = Incoming, 1 = Outgoing
  String? _actingOnId;
  bool _markingNotificationsRead = false;

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
    final outgoingSeed = widget.debugOutgoing;
    if (outgoingSeed != null) {
      _outgoing.addAll(
        outgoingSeed.map(
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
        _loadOutgoing();
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
          _extractError(result.jsonObject, 'Could not load incoming transfer requests.'),
        );
      }
      final parsed = _parseItems(result.jsonObject['items']);
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

  Future<void> _loadOutgoing() async {
    setState(() {
      _loadingOutgoing = true;
      _outgoingError = null;
    });
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/transfers/outgoing',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      if (!result.ok) {
        throw StateError(
          _extractError(result.jsonObject, 'Could not load outgoing transfer requests.'),
        );
      }
      final parsed = _parseItems(result.jsonObject['items']);
      if (!mounted) return;
      setState(() {
        _outgoing
          ..clear()
          ..addAll(parsed);
      });
    } catch (error) {
      if (mounted) setState(() => _outgoingError = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loadingOutgoing = false);
    }
  }

  List<TicketTransferRequest> _parseItems(Object? rawItems) {
    if (rawItems is! List) return const [];
    return rawItems
        .whereType<Map>()
        .map((item) => TicketTransferRequest.fromJson(Map<String, dynamic>.from(item)))
        .toList();
  }

  Future<void> _decide(
    TicketTransferRequest request, {
    required bool accept,
    String? rejectionReason,
  }) async {
    if (_actingOnId != null) return;
    setState(() => _actingOnId = request.id);
    try {
      final action = accept ? 'accept' : 'reject';
      final result = await ApiClient.send(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/tickets/transfers/${request.id}/$action',
        headers: AuthScope.of(context).ticketHeaders(),
        jsonBody: accept ? null : {'rejection_reason': rejectionReason},
      );
      if (!result.ok) {
        throw StateError(
          _extractError(
            result.jsonObject,
            accept ? 'Could not accept transfer request.' : 'Could not reject transfer request.',
          ),
        );
      }
      if (!mounted) return;
      setState(() {
        _incoming.removeWhere((item) => item.id == request.id);
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(accept ? 'Transfer accepted.' : 'Transfer rejected.')),
      );
      await _loadIncoming();
      await _loadOutgoing();
      // A decision resolves the destination office's own "please decide"
      // notification server-side (see accept/reject_ticket_transfer); tell
      // the sidebar badge -- a sibling widget with no other connection to
      // this action -- to refetch so it doesn't stay stale for the rest of
      // this session.
      transferBadgeRefreshTick.value++;
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(_friendlyError(error))),
        );
      }
    } finally {
      if (mounted) setState(() => _actingOnId = null);
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
        url: '${AppConfig.resolvedApiBase}/tickets/notifications/transfers/read-all',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      if (!result.ok) {
        throw StateError(_extractError(result.jsonObject, 'Could not mark notifications read.'));
      }
      transferBadgeRefreshTick.value++;
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Transfer notifications marked read.')),
        );
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(_friendlyError(error))),
        );
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
        builder: (dialogContext) => AlertDialog(
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
      await _decide(request, accept: false, rejectionReason: reason.isEmpty ? null : reason);
    } finally {
      // Runs for every exit path -- Cancel, Reject, barrier/back-button
      // dismissal, and normal completion -- so the controller is always
      // released exactly once.
      controller.dispose();
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    final isOffice = auth.role == 'office';
    final body = _buildBody(context);
    final markReadAction = TextButton(
      onPressed: _markingNotificationsRead ? null : _markTransferNotificationsRead,
      child: Text(_markingNotificationsRead ? 'Marking…' : 'Mark notifications read'),
    );

    if (isOffice) {
      return OfficeScaffold(
        current: StudentNavItem.officeIncomingTransfers,
        title: 'Incoming Transfers',
        description: 'Review office-to-office ticket transfer requests.',
        actions: [markReadAction],
        child: body,
      );
    }
    return AdminScaffold(
      current: StudentNavItem.adminIncomingTransfers,
      title: 'Incoming Transfers',
      description: 'Review office-to-office ticket transfer requests.',
      actions: [markReadAction],
      child: body,
    );
  }

  Widget _buildBody(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _TransferTabToggle(
          selected: _tab,
          onChanged: (value) => setState(() => _tab = value),
        ),
        const SizedBox(height: 16),
        if (_tab == 0) _buildIncomingSection() else _buildOutgoingSection(),
      ],
    );
  }

  Widget _buildIncomingSection() {
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
      children: _incoming
          .map(
            (request) => _TransferCard(
              request: request,
              isIncoming: true,
              busy: _actingOnId == request.id,
              onAccept: () => _decide(request, accept: true),
              onReject: () => _promptReject(request),
            ),
          )
          .toList(),
    );
  }

  Widget _buildOutgoingSection() {
    if (_loadingOutgoing && _outgoing.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 32),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (_outgoingError != null) {
      return _ErrorBanner(message: _outgoingError!, onRetry: _loadOutgoing);
    }
    if (_outgoing.isEmpty) {
      return const _EmptyState(message: 'No outgoing transfer requests.');
    }
    return Column(
      children: _outgoing
          .map((request) => _TransferCard(request: request, isIncoming: false))
          .toList(),
    );
  }
}

class _TransferTabToggle extends StatelessWidget {
  const _TransferTabToggle({required this.selected, required this.onChanged});

  final int selected;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        _toggleButton(context, 'Incoming', 0),
        const SizedBox(width: 8),
        _toggleButton(context, 'Outgoing', 1),
      ],
    );
  }

  Widget _toggleButton(BuildContext context, String label, int value) {
    final isSelected = selected == value;
    return TextButton(
      onPressed: () => onChanged(value),
      style: TextButton.styleFrom(
        backgroundColor: isSelected ? DesignTokens.maroon.withValues(alpha: 0.1) : null,
        foregroundColor: isSelected ? DesignTokens.maroon : DesignTokens.muted,
        textStyle: TextStyle(
          fontWeight: isSelected ? FontWeight.w800 : FontWeight.w600,
        ),
      ),
      child: Text(label),
    );
  }
}

class _TransferCard extends StatelessWidget {
  const _TransferCard({
    required this.request,
    required this.isIncoming,
    this.busy = false,
    this.onAccept,
    this.onReject,
  });

  final TicketTransferRequest request;
  final bool isIncoming;
  final bool busy;
  final VoidCallback? onAccept;
  final VoidCallback? onReject;

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
            Text(request.reason, style: const TextStyle(fontSize: 13, color: DesignTokens.ink)),
          ],
          if (request.rejectionReason != null && request.rejectionReason!.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              'Rejection reason: ${request.rejectionReason}',
              style: const TextStyle(fontSize: 12, color: DesignTokens.muted),
            ),
          ],
          const SizedBox(height: 8),
          Text(
            request.createdAt,
            style: const TextStyle(fontSize: 11, color: DesignTokens.muted),
          ),
          if (isIncoming && request.isPending) ...[
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: busy ? null : onReject,
                  child: const Text('Reject'),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: busy ? null : onAccept,
                  child: busy
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Accept'),
                ),
              ],
            ),
          ],
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
            child: Text(message, style: const TextStyle(color: Color(0xFFB3261E))),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
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
  return message.isEmpty ? 'The backend did not return a usable response.' : message;
}
