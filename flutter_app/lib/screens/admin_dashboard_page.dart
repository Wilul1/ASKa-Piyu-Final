part of 'admin_management_pages.dart';

const int _kAdminDashboardRecentCount = 5;

class AdminDashboardPage extends StatefulWidget {
  const AdminDashboardPage({
    super.key,
    this.debugTickets,
    this.debugError,
    this.debugNow,
  });

  @visibleForTesting
  final List<Map<String, dynamic>>? debugTickets;

  @visibleForTesting
  final String? debugError;

  @visibleForTesting
  final DateTime? debugNow;

  @override
  State<AdminDashboardPage> createState() => _AdminDashboardPageState();
}

class _AdminDashboardPageState extends State<AdminDashboardPage> {
  final List<_AdminTicketEntry> _tickets = [];
  bool _loading = false;
  String? _error;
  bool _requestedInitialLoad = false;

  bool get _usesDebugSeed =>
      widget.debugTickets != null || widget.debugError != null;

  DateTime get _now => widget.debugNow ?? DateTime.now();

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_requestedInitialLoad) return;
    if (_usesDebugSeed) {
      _requestedInitialLoad = true;
      _applyDebugSeed();
      return;
    }
    final auth = AuthScope.of(context);
    if (auth.role == 'admin') {
      _requestedInitialLoad = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _load();
      });
    }
  }

  void _applyDebugSeed() {
    final tickets = (widget.debugTickets ?? const [])
        .map(_AdminTicketEntry.fromJson)
        .toList();
    _sortTickets(tickets);
    _tickets
      ..clear()
      ..addAll(tickets);
    _error = widget.debugError;
    _loading = false;
  }

  void _sortTickets(List<_AdminTicketEntry> tickets) {
    tickets.sort((a, b) {
      final byDate = b.createdAt.compareTo(a.createdAt);
      if (byDate != 0) return byDate;
      return a.id.compareTo(b.id);
    });
  }

  Future<void> _load() async {
    if (_usesDebugSeed) {
      setState(_applyDebugSeed);
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final tickets = await _loadAdminTickets(context);
      _sortTickets(tickets);
      if (!mounted) return;
      setState(() {
        _tickets
          ..clear()
          ..addAll(tickets);
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  int get _openCount =>
      _tickets.where((ticket) => ticket.status == 'Open').length;

  int get _inProgressCount =>
      _tickets.where((ticket) => ticket.status == 'In Progress').length;

  int get _closedCount =>
      _tickets.where((ticket) => ticket.status == 'Closed').length;

  List<_AdminTicketEntry> get _recentTickets =>
      _tickets.take(_kAdminDashboardRecentCount).toList();

  void _openAllTickets({String status = 'All'}) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => AdminAllTicketsPage(initialStatusFilter: status),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final recent = _recentTickets;

    return AdminScaffold(
      current: StudentNavItem.adminDashboard,
      title: 'Admin Dashboard',
      description: 'Monitor support activity and administrative workload.',
      fillBody: true,
      showHeader: false,
      child: ColoredBox(
        color: DesignTokens.adminSurface,
        child: LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= 900;
            final compact = constraints.maxWidth < 900;
            return Align(
              alignment: Alignment.topCenter,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1180),
                child: ListView(
                  key: const Key('admin-dashboard-page'),
                  padding: EdgeInsets.fromLTRB(
                    wide ? 24 : 14,
                    wide ? 20 : 14,
                    wide ? 24 : 14,
                    28,
                  ),
                  children: [
                    if (_loading) const LinearProgressIndicator(minHeight: 3),
                    _AdminDashboardHeader(
                      now: _now,
                      showClock: constraints.maxWidth >= 720,
                    ),
                    const SizedBox(height: 18),
                    if (_error != null) ...[
                      KeyedSubtree(
                        key: const Key('admin-dashboard-error'),
                        child: _AdminNotice(message: _error!),
                      ),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: TextButton(
                          key: const Key('admin-dashboard-retry'),
                          onPressed: _loading ? null : _load,
                          child: const Text('Retry'),
                        ),
                      ),
                      const SizedBox(height: 8),
                    ],
                    _AdminDashboardStatsRow(
                      total: _tickets.length,
                      open: _openCount,
                      inProgress: _inProgressCount,
                      closed: _closedCount,
                      onTotal: () => _openAllTickets(),
                      onOpen: () => _openAllTickets(status: 'Open'),
                      onInProgress: () =>
                          _openAllTickets(status: 'In Progress'),
                      onClosed: () => _openAllTickets(status: 'Closed'),
                    ),
                    const SizedBox(height: 18),
                    _AdminDashboardRecentHeader(
                      stacked: constraints.maxWidth < 560,
                      onViewAll: () => _openAllTickets(),
                    ),
                    const SizedBox(height: 12),
                    if (_loading && _tickets.isEmpty)
                      const _AdminDashboardEmpty(
                        title: 'Loading tickets',
                        message: 'Fetching the latest support tickets.',
                      )
                    else if (recent.isEmpty)
                      const _AdminDashboardEmpty(
                        title: 'No tickets yet.',
                        message:
                            'Student support tickets will appear here after submission.',
                      )
                    else
                      _AdminDashboardRecentTable(
                        tickets: recent,
                        compact: compact,
                        now: _now,
                      ),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _AdminDashboardHeader extends StatelessWidget {
  const _AdminDashboardHeader({
    required this.now,
    required this.showClock,
  });

  final DateTime now;
  final bool showClock;

  @override
  Widget build(BuildContext context) {
    final local = now.toLocal();
    const copy = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Admin Dashboard',
          style: TextStyle(
            color: DesignTokens.ink,
            fontSize: 28,
            fontWeight: FontWeight.w900,
            height: 1.1,
          ),
        ),
        SizedBox(height: 6),
        Text(
          'Monitor support activity and administrative workload.',
          style: TextStyle(
            color: DesignTokens.muted,
            fontSize: 13,
            fontWeight: FontWeight.w600,
            height: 1.35,
          ),
        ),
      ],
    );
    if (!showClock) return copy;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Expanded(child: copy),
        const SizedBox(width: 12),
        KeyedSubtree(
          key: const Key('admin-dashboard-clock'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                _adminFormatAssignedDate(local),
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                _adminDashboardWeekdayTime(local),
                style: const TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _AdminDashboardStatsRow extends StatelessWidget {
  const _AdminDashboardStatsRow({
    required this.total,
    required this.open,
    required this.inProgress,
    required this.closed,
    required this.onTotal,
    required this.onOpen,
    required this.onInProgress,
    required this.onClosed,
  });

  final int total;
  final int open;
  final int inProgress;
  final int closed;
  final VoidCallback onTotal;
  final VoidCallback onOpen;
  final VoidCallback onInProgress;
  final VoidCallback onClosed;

  @override
  Widget build(BuildContext context) {
    final stats = [
      (
        label: 'Total Tickets',
        value: '$total',
        key: 'admin-dashboard-stat-total',
        onTap: onTotal,
      ),
      (
        label: 'Open Tickets',
        value: '$open',
        key: 'admin-dashboard-stat-open',
        onTap: onOpen,
      ),
      (
        label: 'In Progress',
        value: '$inProgress',
        key: 'admin-dashboard-stat-progress',
        onTap: onInProgress,
      ),
      (
        label: 'Closed',
        value: '$closed',
        key: 'admin-dashboard-stat-closed',
        onTap: onClosed,
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final columns = width >= 900
            ? 4
            : width >= 560
                ? 2
                : 1;
        const gap = 12.0;
        final cardWidth = columns == 1
            ? width
            : (width - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: [
            for (final stat in stats)
              SizedBox(
                width: cardWidth,
                child: _AdminDashboardStatCard(
                  label: stat.label,
                  value: stat.value,
                  cardKey: Key(stat.key),
                  onTap: stat.onTap,
                ),
              ),
          ],
        );
      },
    );
  }
}

class _AdminDashboardStatCard extends StatefulWidget {
  const _AdminDashboardStatCard({
    required this.label,
    required this.value,
    required this.cardKey,
    required this.onTap,
  });

  final String label;
  final String value;
  final Key cardKey;
  final VoidCallback onTap;

  @override
  State<_AdminDashboardStatCard> createState() =>
      _AdminDashboardStatCardState();
}

class _AdminDashboardStatCardState extends State<_AdminDashboardStatCard> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: Material(
        color: _hovered ? const Color(0xFFFAF7F7) : Colors.white,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          key: widget.cardKey,
          onTap: widget.onTap,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: _hovered
                    ? const Color(0xFFD7B4B6)
                    : DesignTokens.border,
              ),
              boxShadow: DesignTokens.softShadow(0.03),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.value,
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontSize: 28,
                    fontWeight: FontWeight.w800,
                    height: 1,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  widget.label,
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _AdminDashboardRecentHeader extends StatelessWidget {
  const _AdminDashboardRecentHeader({
    required this.stacked,
    required this.onViewAll,
  });

  final bool stacked;
  final VoidCallback onViewAll;

  @override
  Widget build(BuildContext context) {
    const copy = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Recent Tickets',
          style: TextStyle(
            color: DesignTokens.ink,
            fontSize: 16,
            fontWeight: FontWeight.w800,
          ),
        ),
        SizedBox(height: 4),
        Text(
          'Latest support tickets across all offices.',
          style: TextStyle(
            color: DesignTokens.muted,
            fontSize: 13,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
    final viewAll = InkWell(
      key: const Key('admin-dashboard-view-all'),
      onTap: onViewAll,
      borderRadius: BorderRadius.circular(6),
      child: const Padding(
        padding: EdgeInsets.symmetric(horizontal: 4, vertical: 4),
        child: Text(
          'View all',
          style: TextStyle(
            color: DesignTokens.maroon,
            fontWeight: FontWeight.w800,
            fontSize: 13,
          ),
        ),
      ),
    );
    if (stacked) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          copy,
          const SizedBox(height: 8),
          viewAll,
        ],
      );
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Expanded(child: copy),
        viewAll,
      ],
    );
  }
}

class _AdminDashboardEmpty extends StatelessWidget {
  const _AdminDashboardEmpty({
    required this.title,
    required this.message,
  });

  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('admin-dashboard-empty'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 28),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: DesignTokens.muted),
          ),
        ],
      ),
    );
  }
}

class _AdminDashboardRecentTable extends StatelessWidget {
  const _AdminDashboardRecentTable({
    required this.tickets,
    required this.compact,
    required this.now,
  });

  final List<_AdminTicketEntry> tickets;
  final bool compact;
  final DateTime now;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.03),
      ),
      child: Column(
        children: [
          if (!compact) const _AdminDashboardTableHeader(),
          for (var i = 0; i < tickets.length; i++) ...[
            if (i > 0 || !compact)
              const Divider(height: 1, color: DesignTokens.border),
            compact
                ? _AdminDashboardCardRow(
                    ticket: tickets[i],
                    now: now,
                  )
                : _AdminDashboardTableRow(
                    ticket: tickets[i],
                    now: now,
                  ),
          ],
        ],
      ),
    );
  }
}

class _AdminDashboardTableHeader extends StatelessWidget {
  const _AdminDashboardTableHeader();

  @override
  Widget build(BuildContext context) {
    const style = TextStyle(
      color: DesignTokens.muted,
      fontSize: 11,
      fontWeight: FontWeight.w800,
      letterSpacing: 0.4,
    );
    return const Padding(
      padding: EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: Row(
        children: [
          SizedBox(width: 148, child: Text('TICKET ID', style: style)),
          Expanded(flex: 5, child: Text('SUBJECT', style: style)),
          Expanded(flex: 3, child: Text('OFFICE', style: style)),
          Expanded(flex: 2, child: Text('STATUS', style: style)),
          SizedBox(width: 110, child: Text('CREATED AT', style: style)),
        ],
      ),
    );
  }
}

class _AdminDashboardTableRow extends StatelessWidget {
  const _AdminDashboardTableRow({
    required this.ticket,
    required this.now,
  });

  final _AdminTicketEntry ticket;
  final DateTime now;

  @override
  Widget build(BuildContext context) {
    return Padding(
      key: Key('admin-dashboard-row-${ticket.id}'),
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: Row(
        children: [
          SizedBox(
            width: 148,
            child: Text(
              ticket.id,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: DesignTokens.ink,
                fontWeight: FontWeight.w800,
                fontSize: 12,
              ),
            ),
          ),
          Expanded(
            flex: 5,
            child: Tooltip(
              message: ticket.subject,
              child: Text(
                ticket.subject,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w700,
                  fontSize: 13,
                ),
              ),
            ),
          ),
          Expanded(
            flex: 3,
            child: Text(
              ticket.assignedOffice,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: DesignTokens.ink,
                fontWeight: FontWeight.w600,
                fontSize: 13,
              ),
            ),
          ),
          Expanded(
            flex: 2,
            child: Align(
              alignment: Alignment.centerLeft,
              child: _AllTicketsStatusPill(status: ticket.status),
            ),
          ),
          SizedBox(
            width: 110,
            child: Text(
              _adminDashboardRelativeTime(ticket.createdAt, now),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: DesignTokens.muted,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AdminDashboardCardRow extends StatelessWidget {
  const _AdminDashboardCardRow({
    required this.ticket,
    required this.now,
  });

  final _AdminTicketEntry ticket;
  final DateTime now;

  @override
  Widget build(BuildContext context) {
    return Padding(
      key: Key('admin-dashboard-row-${ticket.id}'),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            ticket.id,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w800,
              fontSize: 12,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            ticket.subject,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w800,
              fontSize: 14,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            ticket.assignedOffice,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          _AllTicketsStatusPill(status: ticket.status),
          const SizedBox(height: 8),
          Text(
            _adminDashboardRelativeTime(ticket.createdAt, now),
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

String _adminDashboardWeekdayTime(DateTime date) {
  const weekdays = [
    'Monday',
    'Tuesday',
    'Wednesday',
    'Thursday',
    'Friday',
    'Saturday',
    'Sunday',
  ];
  return '${weekdays[date.weekday - 1]}, ${_officeDashboardTimeLine(date)}';
}

String _adminDashboardRelativeTime(DateTime createdAt, DateTime now) {
  final local = createdAt.toLocal();
  final current = now.toLocal();
  final diff = current.difference(local);
  if (diff.isNegative) return _adminFormatAssignedDate(local);
  if (diff.inSeconds < 45) return 'just now';
  if (diff.inMinutes < 2) return '1 minute ago';
  if (diff.inMinutes < 60) return '${diff.inMinutes} minutes ago';
  if (diff.inHours < 2) return '1 hour ago';
  if (diff.inHours < 24) return '${diff.inHours} hours ago';
  if (diff.inDays < 2) return '1 day ago';
  if (diff.inDays < 7) return '${diff.inDays} days ago';
  return _adminFormatAssignedDate(local);
}
