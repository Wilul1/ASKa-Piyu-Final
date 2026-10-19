import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/ticket_notification_models.dart';
import '../services/api_client.dart';
import '../widgets/public_site_header.dart';
import '../widgets/student_ui.dart';
import 'my_tickets_page.dart';

/// A student's own inbox of ticket notifications: new office replies,
/// status changes, and reassignments (see TicketNotification's own doc
/// comment for the exact backend guarantee that keeps this free of
/// internal office notes or office-only transfer activity). Reuses the
/// same `GET /tickets/notifications` / `POST .../read-all` / `PATCH
/// .../{id}/read` endpoints MyTicketsPage's own unread banner already
/// calls -- this page is the full inbox, that banner stays a small,
/// dismissible top-3 preview; neither duplicates the other.
class StudentMailboxPage extends StatefulWidget {
  const StudentMailboxPage({super.key, this.debugNotifications});

  /// Seeded notifications skip the network load. Widget tests only.
  @visibleForTesting
  final List<Map<String, dynamic>>? debugNotifications;

  @override
  State<StudentMailboxPage> createState() => _StudentMailboxPageState();
}

class _StudentMailboxPageState extends State<StudentMailboxPage> {
  final List<TicketNotification> _notifications = [];
  int _unreadCount = 0;
  bool _loading = false;
  String? _error;
  bool _requestedInitialLoad = false;
  bool _markingAllRead = false;
  // Per-notification-id busy set -- opening one notification's ticket
  // must never block opening a different one.
  final Set<String> _openingIds = {};

  @override
  void initState() {
    super.initState();
    final seed = widget.debugNotifications;
    if (seed != null) {
      _requestedInitialLoad = true;
      _notifications.addAll(
        seed.map(
          (item) => TicketNotification.fromJson(Map<String, dynamic>.from(item)),
        ),
      );
      _unreadCount = _notifications.where((item) => !item.isRead).length;
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    if (!_requestedInitialLoad && auth.isAuthenticated) {
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
        url: '${AppConfig.resolvedApiBase}/tickets/notifications',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      if (!result.ok) {
        throw StateError(
          ApiClient.extractError(
            result.jsonObject,
            fallback: 'Could not load your mailbox.',
          ),
        );
      }
      final rawItems = result.jsonObject['items'];
      final items =
          rawItems is List
              ? rawItems
                  .whereType<Map>()
                  .map(
                    (item) => TicketNotification.fromJson(
                      Map<String, dynamic>.from(item),
                    ),
                  )
                  .toList()
              : <TicketNotification>[];
      if (!mounted) return;
      setState(() {
        _notifications
          ..clear()
          ..addAll(items);
        _unreadCount = _readInt(result.jsonObject['unread_count']);
      });
    } catch (error) {
      if (mounted) setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _markAllRead() async {
    if (_markingAllRead) return;
    setState(() => _markingAllRead = true);
    try {
      final result = await ApiClient.send(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/tickets/notifications/read-all',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      if (!result.ok) {
        throw StateError(
          ApiClient.extractError(
            result.jsonObject,
            fallback: 'Could not mark notifications read.',
          ),
        );
      }
      await _load();
      // Tells MyTicketsPage's own, separately-fetched notification banner
      // to refresh now rather than waiting for its own periodic poll.
      ticketNotificationRefreshTick.value++;
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(_friendlyError(error))));
      }
    } finally {
      if (mounted) setState(() => _markingAllRead = false);
    }
  }

  // Opening a notification marks that one row read (reusing the existing
  // per-notification endpoint -- the same ordinary "open a message, it's
  // now read" behavior as any inbox), then, if it references a ticket,
  // navigates there. A notification without a ticket id (not expected
  // from any of today's notification-creation call sites, but handled
  // defensively) is just marked read in place.
  Future<void> _openNotification(TicketNotification notification) async {
    if (_openingIds.contains(notification.id)) return;
    setState(() => _openingIds.add(notification.id));
    try {
      if (!notification.isRead) {
        final result = await ApiClient.send(
          method: 'PATCH',
          url:
              '${AppConfig.resolvedApiBase}/tickets/notifications/${notification.id}/read',
          headers: AuthScope.of(context).ticketHeaders(),
        );
        if (result.ok && mounted) {
          setState(() {
            final index = _notifications.indexWhere(
              (item) => item.id == notification.id,
            );
            if (index >= 0) {
              _notifications[index] = TicketNotification(
                id: notification.id,
                ticketId: notification.ticketId,
                type: notification.type,
                title: notification.title,
                body: notification.body,
                isRead: true,
                createdAt: notification.createdAt,
              );
            }
            if (_unreadCount > 0) _unreadCount -= 1;
          });
          // Same reasoning as _markAllRead -- MyTicketsPage's own banner
          // should not have to wait for its own periodic poll.
          ticketNotificationRefreshTick.value++;
        }
      }
      final ticketId = notification.ticketId;
      if (ticketId == null || ticketId.isEmpty || !mounted) return;
      await _openTicket(ticketId);
    } finally {
      if (mounted) setState(() => _openingIds.remove(notification.id));
    }
  }

  Future<void> _openTicket(String ticketId) async {
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/$ticketId',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      if (!result.ok) {
        throw StateError(
          ApiClient.extractError(
            result.jsonObject,
            fallback: 'Could not open this ticket.',
          ),
        );
      }
      if (!mounted) return;
      final ticket = TicketEntry.fromJson(result.jsonObject);
      await Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => TicketDetailsPage(ticket: ticket)),
      );
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(_friendlyError(error))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    if (!auth.isAuthenticated) {
      return const Scaffold(
        backgroundColor: Color(0xFFF3F4F6),
        body: Column(
          children: [
            PublicSiteHeader(mailboxActive: true),
            Expanded(
              child: Center(
                child: Text(
                  'Log in to view your mailbox.',
                  style: TextStyle(color: DesignTokens.muted),
                ),
              ),
            ),
          ],
        ),
      );
    }

    return Scaffold(
      backgroundColor: const Color(0xFFF3F4F6),
      body: Column(
        children: [
          const PublicSiteHeader(mailboxActive: true),
          Expanded(
            child: StudentPage(
              maxWidth: 760,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _MailboxHeader(
                    unreadCount: _unreadCount,
                    marking: _markingAllRead,
                    onMarkAllRead: _unreadCount > 0 ? _markAllRead : null,
                  ),
                  const SizedBox(height: 18),
                  _buildBody(),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_loading && _notifications.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 48),
        child: Center(child: CircularProgressIndicator(color: DesignTokens.maroon)),
      );
    }
    if (_error != null) {
      return _MailboxErrorBanner(message: _error!, onRetry: _load);
    }
    if (_notifications.isEmpty) {
      return const _MailboxEmptyState();
    }
    return Column(
      children: [
        for (final notification in _notifications)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: _NotificationCard(
              notification: notification,
              busy: _openingIds.contains(notification.id),
              onTap: () => _openNotification(notification),
            ),
          ),
      ],
    );
  }
}

class _MailboxHeader extends StatelessWidget {
  const _MailboxHeader({
    required this.unreadCount,
    required this.marking,
    required this.onMarkAllRead,
  });

  final int unreadCount;
  final bool marking;
  final VoidCallback? onMarkAllRead;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final titleRow = Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Mailbox',
              style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.w900,
                color: DesignTokens.ink,
              ),
            ),
            if (unreadCount > 0) ...[
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: DesignTokens.maroon,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  unreadCount > 9 ? '9+' : '$unreadCount',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ],
        );
        final markReadButton = TextButton(
          onPressed: onMarkAllRead,
          child: Text(marking ? 'Marking…' : 'Mark all read'),
        );
        if (constraints.maxWidth >= 420) {
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: titleRow),
              markReadButton,
            ],
          );
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            titleRow,
            const SizedBox(height: 4),
            Align(alignment: Alignment.centerLeft, child: markReadButton),
          ],
        );
      },
    );
  }
}

/// One notification, visually separated via its own bordered card. Unread
/// ones get a small maroon accent and bolder title -- no decorative
/// per-type icon, matching this app's minimal-chrome convention elsewhere.
class _NotificationCard extends StatelessWidget {
  const _NotificationCard({
    required this.notification,
    required this.onTap,
    this.busy = false,
  });

  final TicketNotification notification;
  final VoidCallback onTap;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final unread = !notification.isRead;
    return Opacity(
      opacity: busy ? 0.6 : 1,
      child: Material(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          onTap: busy ? null : onTap,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              border: Border.all(
                color: unread ? DesignTokens.maroon.withValues(alpha: 0.3) : DesignTokens.border,
              ),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 8,
                  height: 8,
                  margin: const EdgeInsets.only(top: 5, right: 10),
                  decoration: BoxDecoration(
                    color: unread ? DesignTokens.maroon : Colors.transparent,
                    shape: BoxShape.circle,
                  ),
                ),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              notification.title,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 14,
                                fontWeight: unread ? FontWeight.w800 : FontWeight.w600,
                                color: DesignTokens.ink,
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Flexible(
                            child: Text(
                              _formatNotificationDate(notification.createdAt),
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
                        notification.body,
                        style: const TextStyle(fontSize: 13, color: DesignTokens.muted),
                      ),
                      if ((notification.ticketId ?? '').isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Text(
                          'Ticket #${notification.ticketId}',
                          style: const TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: DesignTokens.muted,
                          ),
                        ),
                      ],
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

class _MailboxEmptyState extends StatelessWidget {
  const _MailboxEmptyState();

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.symmetric(vertical: 48, horizontal: 24),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'Mailbox is empty',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w800,
                color: DesignTokens.ink,
              ),
            ),
            SizedBox(height: 6),
            Text(
              'Updates on your tickets -- new replies, status changes, and '
              'reassignments -- will appear here.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 13, color: DesignTokens.muted),
            ),
          ],
        ),
      ),
    );
  }
}

class _MailboxErrorBanner extends StatelessWidget {
  const _MailboxErrorBanner({required this.message, required this.onRetry});

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

int _readInt(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse(value?.toString() ?? '') ?? 0;
}

/// Readable "Oct 13" form -- matches this app's existing manual
/// month-name convention (no `intl` dependency), duplicated locally since
/// this is a separate library from the other screens that already have
/// their own copy.
String _formatNotificationDate(String iso) {
  final parsed = DateTime.tryParse(iso);
  if (parsed == null) return iso;
  final local = parsed.toLocal();
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  return '${months[local.month - 1]} ${local.day}';
}

String _friendlyError(Object error) {
  final message = error.toString().replaceFirst('Bad state: ', '').trim();
  return message.isEmpty
      ? 'The backend did not return a usable response.'
      : message;
}
