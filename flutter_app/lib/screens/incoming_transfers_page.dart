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
/// A single page, reads like an email inbox: an Incoming/Outgoing segmented
/// switch inside the page itself picks which list is shown (never a sibling
/// page or a separate sidebar nav item -- the Office Dashboard's own
/// Mailbox button is the one external entry point). Selecting a card opens
/// its details; Accept/Reject live only there, and only for an incoming,
/// still-Pending request.
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

enum _MailboxTab { incoming, outgoing }

class _IncomingTransfersPageState extends State<IncomingTransfersPage> {
  _MailboxTab _tab = _MailboxTab.incoming;

  final List<TicketTransferRequest> _incoming = [];
  bool _loadingIncoming = false;
  String? _incomingError;
  bool _requestedIncomingLoad = false;

  final List<TicketTransferRequest> _outgoing = [];
  bool _loadingOutgoing = false;
  String? _outgoingError;
  bool _requestedOutgoingLoad = false;

  bool _markingNotificationsRead = false;
  // Per-request-id busy set, not a single id: a decision on one request
  // must never block deciding a *different* one -- only a second decision
  // on the SAME id while its own call is still in flight. Only ever
  // populated for incoming requests -- outgoing ones are never decidable.
  final Set<String> _actingOnIds = {};

  @override
  void initState() {
    super.initState();
    final incomingSeed = widget.debugIncoming;
    if (incomingSeed != null) {
      _requestedIncomingLoad = true;
      _incoming.addAll(
        incomingSeed.map(
          (item) =>
              TicketTransferRequest.fromJson(Map<String, dynamic>.from(item)),
        ),
      );
    }
    final outgoingSeed = widget.debugOutgoing;
    if (outgoingSeed != null) {
      _requestedOutgoingLoad = true;
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
    if (!_requestedIncomingLoad && canLoad) {
      _requestedIncomingLoad = true;
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
          _extractError(
            result.jsonObject,
            'Could not load outgoing transfer requests.',
          ),
        );
      }
      final parsed = _parseTransferItems(result.jsonObject['items']);
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

  // Switching tabs never pushes a new route -- the whole point of the
  // segmented switch is that both lists live on this one page. Outgoing's
  // own load is lazy, triggered the first time the tab is actually
  // selected (mirroring the previous separate page's own mount-triggered
  // load), so a user who never looks at Outgoing never pays for that
  // request; switching back and forth afterward never refetches.
  void _selectTab(_MailboxTab tab) {
    if (_tab == tab) return;
    setState(() => _tab = tab);
    if (tab == _MailboxTab.outgoing && !_requestedOutgoingLoad) {
      final auth = AuthScope.of(context);
      if (auth.role == 'office' || auth.role == 'admin') {
        _requestedOutgoingLoad = true;
        _loadOutgoing();
      }
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
      // the sidebar/dashboard badge -- a sibling widget with no other
      // connection to this action -- to refetch so it doesn't stay stale
      // for the rest of this session.
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

  // Single shared action for both tabs -- a source office actually learns
  // a transfer it sent was accepted/rejected via a notification addressed
  // to it (type "transfer_accepted"/"transfer_rejected", see accept/
  // reject_ticket_transfer in ticketing.py), never to the destination; the
  // destination's own "please decide" notification is the one a decision
  // itself resolves. One explicit, user-initiated bulk action reachable
  // regardless of which tab is open covers both, rather than requiring a
  // source office to find it only under a specific tab.
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

  /// Opens the message's details. A Pending INCOMING request's dialog
  /// returns 'accept'/'reject'; an outgoing request's dialog never offers
  /// those actions regardless of status (the caller never decides their
  /// own sent request), so `action` is only ever meaningful when
  /// `isIncoming` is true. The actual decision runs only after the dialog
  /// has already closed, exactly mirroring how `_promptReject` already
  /// hands off from its own sub-dialog.
  Future<void> _openDetails(
    TicketTransferRequest request, {
    required bool isIncoming,
  }) async {
    // A decision for this id is already in flight -- the card itself is
    // disabled while that's true (see _buildListArea), but this is a
    // second, defensive guard against reopening details for it by any
    // other path.
    if (isIncoming && _actingOnIds.contains(request.id)) return;
    final action = await showDialog<String>(
      context: context,
      builder:
          (_) => _TransferDetailsDialog(request: request, isIncoming: isIncoming),
    );
    if (!mounted || action == null || !isIncoming) return;
    if (action == 'accept') {
      await _decide(request, accept: true);
    } else if (action == 'reject') {
      await _promptReject(request);
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    final isOffice = auth.role == 'office';
    final body = _MailboxBody(
      tab: _tab,
      onSelectTab: _selectTab,
      marking: _markingNotificationsRead,
      onMarkRead:
          _markingNotificationsRead ? null : _markTransferNotificationsRead,
      listArea: _buildListArea(),
    );

    if (isOffice) {
      return OfficeScaffold(
        current: StudentNavItem.officeIncomingTransfers,
        title: 'Office Mailbox',
        description: 'Manage ticket transfer requests',
        fillBody: true,
        showHeader: false,
        child: body,
      );
    }
    return AdminScaffold(
      current: StudentNavItem.adminIncomingTransfers,
      title: 'Office Mailbox',
      description: 'Manage ticket transfer requests',
      fillBody: true,
      showHeader: false,
      child: body,
    );
  }

  Widget _buildListArea() {
    final isIncoming = _tab == _MailboxTab.incoming;
    final loading = isIncoming ? _loadingIncoming : _loadingOutgoing;
    final error = isIncoming ? _incomingError : _outgoingError;
    final items = isIncoming ? _incoming : _outgoing;
    final onRetry = isIncoming ? _loadIncoming : _loadOutgoing;

    if (loading && items.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (error != null) {
      return _ErrorBanner(message: error, onRetry: onRetry);
    }
    if (items.isEmpty) {
      return _MailboxEmptyState(
        isIncoming: isIncoming,
        onSwitchTab:
            () => _selectTab(
              isIncoming ? _MailboxTab.outgoing : _MailboxTab.incoming,
            ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.only(bottom: 16),
      itemCount: items.length,
      itemBuilder: (context, index) {
        final request = items[index];
        final busy = isIncoming && _actingOnIds.contains(request.id);
        return _MailboxCard(
          request: request,
          isIncoming: isIncoming,
          busy: busy,
          onTap:
              busy
                  ? null
                  : () => _openDetails(request, isIncoming: isIncoming),
        );
      },
    );
  }
}

/// The page's own content: a responsive header (title + unread badge +
/// the compact mark-read action), the Incoming/Outgoing switch, then
/// whichever list/loading/error/empty state is current. OfficeScaffold/
/// AdminScaffold are used with `showHeader: false` here -- their own
/// title/description slot only ever takes a plain string, with no room
/// for the badge or switch this page needs, so this builds its own header
/// instead (the same choice OfficeDashboardPage already makes for its
/// own, differently-shaped header).
class _MailboxBody extends StatelessWidget {
  const _MailboxBody({
    required this.tab,
    required this.onSelectTab,
    required this.marking,
    required this.onMarkRead,
    required this.listArea,
  });

  final _MailboxTab tab;
  final ValueChanged<_MailboxTab> onSelectTab;
  final bool marking;
  final VoidCallback? onMarkRead;
  final Widget listArea;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 900;
        return Padding(
          padding: EdgeInsets.fromLTRB(
            wide ? 24 : 14,
            wide ? 20 : 14,
            wide ? 24 : 14,
            0,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _MailboxHeader(marking: marking, onMarkRead: onMarkRead),
              const SizedBox(height: 14),
              _MailboxTabSwitch(tab: tab, onChanged: onSelectTab),
              const SizedBox(height: 14),
              Expanded(child: listArea),
            ],
          ),
        );
      },
    );
  }
}

class _MailboxHeader extends StatelessWidget {
  const _MailboxHeader({required this.marking, required this.onMarkRead});

  final bool marking;
  final VoidCallback? onMarkRead;

  static const double _wrapBreakpoint = 520;

  @override
  Widget build(BuildContext context) {
    final titleRow = Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Flexible(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: const [
                  Text(
                    'Office Mailbox',
                    style: TextStyle(
                      color: DesignTokens.ink,
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  TransferBadge(),
                ],
              ),
              const SizedBox(height: 4),
              const Text(
                'Manage ticket transfer requests',
                style: TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      ],
    );
    final markReadButton = TextButton(
      onPressed: onMarkRead,
      child: Text(marking ? 'Marking…' : 'Mark all read'),
    );

    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth >= _wrapBreakpoint) {
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: titleRow),
              const SizedBox(width: 12),
              markReadButton,
            ],
          );
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            titleRow,
            const SizedBox(height: 8),
            Align(alignment: Alignment.centerLeft, child: markReadButton),
          ],
        );
      },
    );
  }
}

/// Incoming/Outgoing switch living inside the page, not a route push --
/// selecting a segment just swaps which list `_buildListArea` shows.
/// Plain Row of two Expanded, borderless-except-for-the-pill InkWells
/// rather than Material's SegmentedButton, to match this app's existing
/// hand-styled (not Material-3-default) chrome elsewhere.
class _MailboxTabSwitch extends StatelessWidget {
  const _MailboxTabSwitch({required this.tab, required this.onChanged});

  final _MailboxTab tab;
  final ValueChanged<_MailboxTab> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: DesignTokens.bgGrey,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Row(
        children: [
          Expanded(
            child: _MailboxTabSegment(
              label: 'Incoming',
              selected: tab == _MailboxTab.incoming,
              onTap: () => onChanged(_MailboxTab.incoming),
            ),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: _MailboxTabSegment(
              label: 'Outgoing',
              selected: tab == _MailboxTab.outgoing,
              onTap: () => onChanged(_MailboxTab.outgoing),
            ),
          ),
        ],
      ),
    );
  }
}

class _MailboxTabSegment extends StatelessWidget {
  const _MailboxTabSegment({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? DesignTokens.maroon : Colors.transparent,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 9),
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w800,
              color: selected ? Colors.white : DesignTokens.muted,
            ),
          ),
        ),
      ),
    );
  }
}

/// One email-style card, used for both the Incoming and Outgoing lists.
/// The bold "sender" line is the OTHER office relative to the viewer --
/// the source office for an incoming request, the destination office for
/// an outgoing one -- matching how an inbox always names the other party,
/// never the viewer's own office. Tapping anywhere on the card opens its
/// details; Accept/Reject never appear inline here, only in that dialog,
/// and only for an incoming, still-Pending request.
class _MailboxCard extends StatelessWidget {
  const _MailboxCard({
    required this.request,
    required this.isIncoming,
    required this.onTap,
    this.busy = false,
  });

  final TicketTransferRequest request;
  final bool isIncoming;

  /// Null (not just a no-op callback) while `busy` is true, so the card is
  /// genuinely un-tappable -- not just visually dimmed -- during its own
  /// in-flight accept/reject decision.
  final VoidCallback? onTap;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final otherOfficeName =
        isIncoming ? request.sourceOfficeName : request.destinationOfficeName;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: Opacity(
            opacity: busy ? 0.6 : 1,
            child: Container(
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
                                otherOfficeName,
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
                            // forces a RenderFlex overflow on narrow
                            // screens regardless of how short the string is.
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
                              // Ticket title would belong here too, but the
                              // backend's TicketTransferRequestSchema never
                              // includes one (ticket_id only) -- shown only
                              // when actually available, never invented.
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
                            _StatusBadge(status: request.status),
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
      ),
    );
  }
}

/// A message's full details, opened from _MailboxCard. An incoming,
/// Pending request's dialog returns 'accept'/'reject'; the actual decision
/// runs only after this dialog has already closed (see
/// IncomingTransfersPage._openDetails), so this widget never needs its own
/// busy/error state for the decision itself. An outgoing request never
/// offers Accept/Reject regardless of status -- the caller never decides
/// their own sent request.
class _TransferDetailsDialog extends StatelessWidget {
  const _TransferDetailsDialog({
    required this.request,
    required this.isIncoming,
  });

  final TicketTransferRequest request;
  final bool isIncoming;

  @override
  Widget build(BuildContext context) {
    final otherOfficeName =
        isIncoming ? request.sourceOfficeName : request.destinationOfficeName;
    final canDecide = isIncoming && request.isPending;
    // Reading-pane layout: the other office and status read like an
    // opened message's header, a divider separates header from body, the
    // reason is the message body, and the rest is footer metadata -- same
    // fields as the card (ticket reference, destination, requested time,
    // rejection reason), just ordered like a message, not a form.
    return AlertDialog(
      title: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  otherOfficeName,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 8),
              _StatusBadge(status: request.status),
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
        if (canDecide) ...[
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

/// A small filled pill, not just colored text -- "clear status badge" per
/// design, legible at a glance across Pending/Accepted/Rejected.
class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      'Accepted' => const Color(0xFF1B7F3A),
      'Rejected' => const Color(0xFFB3261E),
      _ => DesignTokens.maroon,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(
        status,
        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: color),
      ),
    );
  }
}

class _MailboxEmptyState extends StatelessWidget {
  const _MailboxEmptyState({
    required this.isIncoming,
    required this.onSwitchTab,
  });

  final bool isIncoming;
  final VoidCallback onSwitchTab;

  @override
  Widget build(BuildContext context) {
    final title = isIncoming ? 'Inbox is clear' : 'No outgoing requests yet';
    final description =
        isIncoming
            ? 'New transfer requests from other offices will appear here.'
            : 'Transfer requests your office sends to other offices will appear here.';
    final actionLabel =
        isIncoming ? 'View outgoing requests' : 'View incoming requests';
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 32, horizontal: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w800,
                color: DesignTokens.ink,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              description,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 13, color: DesignTokens.muted),
            ),
            const SizedBox(height: 12),
            TextButton(onPressed: onSwitchTab, child: Text(actionLabel)),
          ],
        ),
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

/// Short "Oct 13" form for the mailbox card, which shares its line with
/// the other office's name -- the full date+time form
/// (_formatRequestTimestamp) is too wide there on narrow screens. The full
/// form is still shown once the message is open (see
/// _TransferDetailsDialog), matching how a mail client's list view uses a
/// compact date and the opened message shows the full one.
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
