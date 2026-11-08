import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/ticket_notification_models.dart';
import '../services/api_client.dart';
import '../services/eye_comfort.dart';
import '../widgets/phone_layout.dart';
import '../widgets/public_site_header.dart';
import '../widgets/student_ui.dart';
import 'my_tickets_page.dart';

const _mailboxNavy = Color(0xFF1B2333);
const _mailboxMuted = Color(0xFF6B7280);
const _mailboxPageBg = Color(0xFFF7F5F6);
const _mailboxCardBorder = Color(0xFFE8EAEE);

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
    final eyeComfort = EyeComfortScope.isEnabled(context);
    final pageBg = eyeComfort ? EyeComfortColors.bg : _mailboxPageBg;

    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final isWide = width >= kDesktopSplitBreakpoint;
        final wideDesktop = width >= 1200;
        final side = wideDesktop
            ? width * DesignTokens.kbDesktopSideInset
            : (isWide ? 28.0 : 16.0);
        final pagePadding = EdgeInsets.fromLTRB(
          side,
          isWide ? 42 : 22,
          side,
          isWide ? 72 : 56,
        );

        final body = !auth.isAuthenticated
            ? Padding(
                padding: pagePadding,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _MailboxHeader(
                      isWide: isWide,
                      unreadCount: 0,
                      marking: false,
                      onMarkAllRead: null,
                    ),
                    SizedBox(height: isWide ? 22 : 18),
                    const StudentPanel(
                      padding: EdgeInsets.symmetric(
                        horizontal: 22,
                        vertical: 42,
                      ),
                      shadow: false,
                      child: Center(
                        child: Text(
                          'Log in to view your mailbox.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: DesignTokens.muted),
                        ),
                      ),
                    ),
                  ],
                ),
              )
            : RefreshIndicator(
                onRefresh: _load,
                color: DesignTokens.maroon,
                child: SingleChildScrollView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: pagePadding,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _MailboxHeader(
                        isWide: isWide,
                        unreadCount: _unreadCount,
                        marking: _markingAllRead,
                        onMarkAllRead:
                            _unreadCount > 0 ? _markAllRead : null,
                      ),
                      SizedBox(height: isWide ? 22 : 18),
                      _buildBody(),
                    ],
                  ),
                ),
              );

        return Scaffold(
          backgroundColor: pageBg,
          body: Stack(
            children: [
              const Positioned.fill(
                child: IgnorePointer(
                  child: CustomPaint(painter: _MailboxWavePainter()),
                ),
              ),
              Column(
                children: [
                  const PublicSiteHeader(mailboxActive: true),
                  Expanded(child: body),
                ],
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildBody() {
    if (_loading && _notifications.isEmpty) {
      return const StudentPanel(
        padding: EdgeInsets.symmetric(vertical: 44),
        shadow: false,
        child: Center(
          child: CircularProgressIndicator(color: DesignTokens.maroon),
        ),
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
            padding: const EdgeInsets.only(bottom: 12),
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
    required this.isWide,
    required this.unreadCount,
    required this.marking,
    required this.onMarkAllRead,
  });

  final bool isWide;
  final int unreadCount;
  final bool marking;
  final VoidCallback? onMarkAllRead;

  @override
  Widget build(BuildContext context) {
    final heading = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Flexible(
              child: Text(
                'Mailbox',
                style: TextStyle(
                  fontSize: isWide ? 40 : 30,
                  height: 1.12,
                  fontWeight: FontWeight.w800,
                  color: _mailboxNavy,
                  letterSpacing: -0.5,
                ),
              ),
            ),
            if (unreadCount > 0) ...[
              const SizedBox(width: 10),
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
        ),
        const SizedBox(height: 8),
        const Text(
          'Stay up to date on your support tickets.',
          style: TextStyle(
            fontSize: 15.5,
            height: 1.4,
            color: _mailboxMuted,
            fontWeight: FontWeight.w500,
          ),
        ),
        const SizedBox(height: 12),
        const Align(
          alignment: Alignment.centerLeft,
          child: SizedBox(
            width: 85,
            height: 3,
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: DesignTokens.maroon,
                borderRadius: BorderRadius.all(Radius.circular(2)),
              ),
            ),
          ),
        ),
      ],
    );

    final markReadButton = TextButton(
      onPressed: onMarkAllRead,
      style: TextButton.styleFrom(
        foregroundColor: DesignTokens.maroon,
        disabledForegroundColor: const Color(0xFF9AA3B2),
        textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
      ),
      child: Text(marking ? 'Marking…' : 'Mark all read'),
    );

    if (!isWide) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          heading,
          const SizedBox(height: 8),
          Align(alignment: Alignment.centerLeft, child: markReadButton),
        ],
      );
    }

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(child: heading),
        const SizedBox(width: 16),
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: markReadButton,
        ),
      ],
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
    final eyeComfort = EyeComfortScope.isEnabled(context);
    final cardBg = eyeComfort ? EyeComfortColors.cardBg : Colors.white;
    final border = eyeComfort ? EyeComfortColors.border : _mailboxCardBorder;
    final ticketId = notification.ticketId ?? '';
    return Opacity(
      opacity: busy ? 0.6 : 1,
      child: Material(
        color: cardBg,
        borderRadius: BorderRadius.circular(18),
        child: InkWell(
          onTap: busy ? null : onTap,
          borderRadius: BorderRadius.circular(18),
          child: Ink(
            decoration: BoxDecoration(
              color: cardBg,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(
                color: unread
                    ? DesignTokens.maroon.withValues(alpha: 0.28)
                    : border,
              ),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.035),
                  blurRadius: 12,
                  offset: const Offset(0, 4),
                ),
              ],
            ),
            child: IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Container(
                    width: 5,
                    decoration: BoxDecoration(
                      color: unread
                          ? DesignTokens.maroon
                          : const Color(0xFFE8EAEE),
                      borderRadius: const BorderRadius.only(
                        topLeft: Radius.circular(18),
                        bottomLeft: Radius.circular(18),
                      ),
                    ),
                  ),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(16, 16, 8, 16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            notification.title,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontSize: 15.5,
                              height: 1.25,
                              fontWeight:
                                  unread ? FontWeight.w800 : FontWeight.w600,
                              color: _mailboxNavy,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            notification.body,
                            style: const TextStyle(
                              fontSize: 13.5,
                              height: 1.4,
                              color: _mailboxMuted,
                            ),
                          ),
                          const SizedBox(height: 10),
                          Wrap(
                            spacing: 12,
                            runSpacing: 4,
                            crossAxisAlignment: WrapCrossAlignment.center,
                            children: [
                              Text(
                                _formatNotificationDate(notification.createdAt),
                                style: const TextStyle(
                                  fontSize: 13,
                                  color: _mailboxMuted,
                                ),
                              ),
                              if (ticketId.isNotEmpty)
                                Text(
                                  'Ticket #$ticketId',
                                  style: const TextStyle(
                                    fontSize: 13,
                                    fontWeight: FontWeight.w700,
                                    color: DesignTokens.maroon,
                                  ),
                                ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                  if (busy)
                    const Padding(
                      padding: EdgeInsets.only(right: 14),
                      child: Center(
                        child: SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      ),
                    )
                  else
                    const Padding(
                      padding: EdgeInsets.only(right: 10),
                      child: Icon(
                        Icons.chevron_right_rounded,
                        color: Color(0xFF9AA3B2),
                        size: 22,
                      ),
                    ),
                ],
              ),
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
    return const StudentPanel(
      padding: EdgeInsets.symmetric(horizontal: 22, vertical: 42),
      shadow: false,
      child: Column(
        children: [
          Text(
            'Mailbox is empty',
            style: TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w900,
              fontSize: 18,
            ),
          ),
          SizedBox(height: 6),
          Text(
            'Updates on your tickets -- new replies, status changes, and '
            'reassignments -- will appear here.',
            textAlign: TextAlign.center,
            style: TextStyle(color: DesignTokens.muted, height: 1.35),
          ),
        ],
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
        color: const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFFED7AA)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline_rounded, color: Color(0xFFC2410C)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(fontSize: 13, color: Color(0xFF9A3412)),
            ),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}

class _MailboxWavePainter extends CustomPainter {
  const _MailboxWavePainter();

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;

    void band(Path path, Color color) {
      canvas.drawPath(path, Paint()..color = color);
    }

    band(
      Path()
        ..moveTo(0, h * 0.62)
        ..cubicTo(w * 0.08, h * 0.48, w * 0.22, h * 0.78, w * 0.36, h * 0.70)
        ..cubicTo(w * 0.24, h * 0.92, w * 0.10, h * 1.02, 0, h)
        ..close(),
      const Color(0xFFF6E4E8).withValues(alpha: 0.95),
    );
    band(
      Path()
        ..moveTo(0, h * 0.74)
        ..cubicTo(w * 0.10, h * 0.60, w * 0.28, h * 0.88, w * 0.42, h * 0.80)
        ..cubicTo(w * 0.30, h * 0.98, w * 0.12, h * 1.05, 0, h * 0.96)
        ..close(),
      const Color(0xFFF3D4DB).withValues(alpha: 0.72),
    );
    band(
      Path()
        ..moveTo(0, h * 0.84)
        ..cubicTo(w * 0.06, h * 0.76, w * 0.16, h * 0.96, w * 0.28, h * 0.90)
        ..cubicTo(w * 0.18, h * 1.02, w * 0.08, h * 1.04, 0, h)
        ..close(),
      const Color(0xFFE8C2CB).withValues(alpha: 0.45),
    );
  }

  @override
  bool shouldRepaint(covariant _MailboxWavePainter oldDelegate) => false;
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
