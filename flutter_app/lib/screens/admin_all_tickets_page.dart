part of 'admin_management_pages.dart';

const int _kAllTicketsPageSize = 5;

class AdminAllTicketsPage extends StatefulWidget {
  const AdminAllTicketsPage({
    super.key,
    this.initialStatusFilter = 'All',
    this.debugTickets,
    this.debugOffices,
    this.debugError,
  });

  final String initialStatusFilter;

  @visibleForTesting
  final List<Map<String, dynamic>>? debugTickets;

  @visibleForTesting
  final List<Map<String, dynamic>>? debugOffices;

  @visibleForTesting
  final String? debugError;

  @override
  State<AdminAllTicketsPage> createState() => _AdminAllTicketsPageState();
}

class _AdminAllTicketsPageState extends State<AdminAllTicketsPage> {
  final List<_AdminTicketEntry> _tickets = [];
  final List<_AdminOfficeEntry> _offices = [];
  final TextEditingController _searchCtrl = TextEditingController();
  bool _loading = false;
  String? _error;
  late String _statusFilter;
  String _priorityFilter = 'All';
  String _officeFilter = 'All';
  bool _requestedInitialLoad = false;
  int _page = 1;

  bool get _usesDebugSeed =>
      widget.debugTickets != null ||
      widget.debugOffices != null ||
      widget.debugError != null;

  @override
  void initState() {
    super.initState();
    _statusFilter = widget.initialStatusFilter;
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

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
        if (mounted) _loadTickets();
      });
    }
  }

  void _applyDebugSeed() {
    final tickets = (widget.debugTickets ?? const [])
        .map((item) => _AdminTicketEntry.fromJson(item))
        .toList();
    final offices = (widget.debugOffices ?? const [])
        .map(_AdminOfficeEntry.fromJson)
        .toList();
    _sortTickets(tickets);
    _tickets
      ..clear()
      ..addAll(tickets);
    _offices
      ..clear()
      ..addAll(offices);
    _error = widget.debugError;
    _loading = false;
    _page = _safePageFor(_filteredTickets.length);
  }

  void _sortTickets(List<_AdminTicketEntry> tickets) {
    tickets.sort((a, b) {
      final byDate = b.createdAt.compareTo(a.createdAt);
      if (byDate != 0) return byDate;
      return a.id.compareTo(b.id);
    });
  }

  Future<void> _loadTickets() async {
    if (_usesDebugSeed) {
      setState(_applyDebugSeed);
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      final data = _decodeObject(result.body);
      final statusCode = result.statusCode;
      if (statusCode < 200 || statusCode >= 300) {
        throw StateError(_extractError(data, 'Could not load tickets.'));
      }
      final items = data['items'] is List ? data['items'] as List : const [];
      final tickets = items
          .whereType<Map>()
          .map((item) =>
              _AdminTicketEntry.fromJson(Map<String, dynamic>.from(item)))
          .toList();
      _sortTickets(tickets);
      var offices = <_AdminOfficeEntry>[];
      try {
        offices = await _loadAdminOffices(context);
      } catch (_) {
        offices = const [];
      }
      if (!mounted) return;
      setState(() {
        _tickets
          ..clear()
          ..addAll(tickets);
        _offices
          ..clear()
          ..addAll(offices);
        _page = _safePageFor(_filteredTickets.length);
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<_AdminTicketEntry> _patchTicket(
    _AdminTicketEntry ticket,
    Map<String, dynamic> payload,
  ) async {
    final result = await ApiClient.send(
      method: 'PATCH',
      url: '${AppConfig.resolvedApiBase}/tickets/${ticket.id}',
      headers: {...AuthScope.of(context).ticketHeaders()},
      jsonBody: payload,
    );
    final data = _decodeObject(result.body);
    final statusCode = result.statusCode;
    if (statusCode < 200 || statusCode >= 300) {
      throw StateError(_extractError(data, 'Could not update ticket.'));
    }
    final updated = _AdminTicketEntry.fromJson(data);
    _replaceTicket(updated);
    return updated;
  }

  Future<_AdminTicketEntry> _replyToTicket(
    _AdminTicketEntry ticket,
    String message,
  ) async {
    final result = await ApiClient.send(
      method: 'POST',
      url: '${AppConfig.resolvedApiBase}/tickets/${ticket.id}/replies',
      headers: {...AuthScope.of(context).ticketHeaders()},
      jsonBody: {'message': message},
    );
    final data = _decodeObject(result.body);
    final statusCode = result.statusCode;
    if (statusCode < 200 || statusCode >= 300) {
      throw StateError(_extractError(data, 'Could not send reply.'));
    }
    final updated = _AdminTicketEntry.fromJson(data);
    _replaceTicket(updated);
    return updated;
  }

  void _replaceTicket(_AdminTicketEntry updated) {
    setState(() {
      final index = _tickets.indexWhere((ticket) => ticket.id == updated.id);
      if (index == -1) {
        _tickets.insert(0, updated);
      } else {
        _tickets[index] = updated;
      }
      _sortTickets(_tickets);
    });
  }

  Future<void> _openTicketDetails(_AdminTicketEntry ticket) async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => _AdminTicketDetailsDialog(
        ticket: ticket,
        offices: _officeOptions(includeAll: false),
        onUpdate: (payload) => _patchTicket(ticket, payload),
        onReply: (message) => _replyToTicket(ticket, message),
      ),
    );
  }

  List<_AdminTicketEntry> get _filteredTickets {
    return _tickets
        .where((ticket) => ticket.matches(
              _searchCtrl.text,
              _statusFilter,
              _priorityFilter,
              _officeFilter,
            ))
        .toList();
  }

  int _pageCountFor(int count) {
    if (count <= 0) return 1;
    return ((count + _kAllTicketsPageSize - 1) / _kAllTicketsPageSize).floor();
  }

  int _safePageFor(int count) {
    return _page.clamp(1, _pageCountFor(count));
  }

  List<_AdminTicketEntry> get _pageTickets {
    final filtered = _filteredTickets;
    final page = _safePageFor(filtered.length);
    final start = (page - 1) * _kAllTicketsPageSize;
    if (start >= filtered.length) return const [];
    final end = (start + _kAllTicketsPageSize).clamp(0, filtered.length);
    return filtered.sublist(start, end);
  }

  void _resetPage() => setState(() => _page = 1);

  void _resetFilters() {
    setState(() {
      _officeFilter = 'All';
      _statusFilter = 'All';
      _priorityFilter = 'All';
      _page = 1;
    });
  }

  List<String> _officeOptions({bool includeAll = true}) {
    final names = <String>{
      ..._offices.map((office) => office.name).where((name) => name.trim().isNotEmpty),
      ..._tickets
          .map((ticket) => ticket.assignedOffice)
          .where((name) => name.trim().isNotEmpty),
    }.toList()
      ..sort();
    return [if (includeAll) 'All', ...names];
  }

  int get _openCount =>
      _tickets.where((ticket) => ticket.status == 'Open').length;

  int get _inProgressCount =>
      _tickets.where((ticket) => ticket.status == 'In Progress').length;

  int get _closedCount =>
      _tickets.where((ticket) => ticket.status == 'Closed').length;

  @override
  Widget build(BuildContext context) {
    final filtered = _filteredTickets;
    final pageTickets = _pageTickets;
    final page = _safePageFor(filtered.length);
    final pageCount = _pageCountFor(filtered.length);

    return AdminScaffold(
      current: StudentNavItem.adminAllTickets,
      title: 'All Tickets',
      description:
          'Review and manage all student support tickets across offices and statuses.',
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
                  key: const Key('admin-all-tickets-page'),
                  padding: EdgeInsets.fromLTRB(
                    wide ? 24 : 14,
                    wide ? 20 : 14,
                    wide ? 24 : 14,
                    28,
                  ),
                  children: [
                    if (_loading) const LinearProgressIndicator(minHeight: 3),
                    if (_error != null) ...[
                      KeyedSubtree(
                        key: const Key('admin-all-tickets-error'),
                        child: _AdminNotice(
                          icon: Icons.info_outline_rounded,
                          message: _error!,
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],
                    _AllTicketsHeader(
                      stacked: constraints.maxWidth < 760,
                      searchCtrl: _searchCtrl,
                      onSearchChanged: (_) => _resetPage(),
                    ),
                    const SizedBox(height: 16),
                    _AllTicketsStatsRow(
                      total: _tickets.length,
                      open: _openCount,
                      inProgress: _inProgressCount,
                      closed: _closedCount,
                    ),
                    const SizedBox(height: 14),
                    _AllTicketsFilterBar(
                      officeFilter: _officeFilter,
                      statusFilter: _statusFilter,
                      priorityFilter: _priorityFilter,
                      officeOptions: _officeOptions(),
                      stacked: constraints.maxWidth < 820,
                      onOfficeChanged: (value) {
                        setState(() {
                          _officeFilter = value;
                          _page = 1;
                        });
                      },
                      onStatusChanged: (value) {
                        setState(() {
                          _statusFilter = value;
                          _page = 1;
                        });
                      },
                      onPriorityChanged: (value) {
                        setState(() {
                          _priorityFilter = value;
                          _page = 1;
                        });
                      },
                      onReset: _resetFilters,
                    ),
                    const SizedBox(height: 14),
                    if (_loading && _tickets.isEmpty)
                      const _AllTicketsEmpty(
                        title: 'Loading tickets',
                        message: 'Fetching the admin ticket queue.',
                      )
                    else if (filtered.isEmpty)
                      _AllTicketsEmpty(
                        title: _tickets.isEmpty
                            ? 'No tickets yet'
                            : 'No matching tickets',
                        message: _tickets.isEmpty
                            ? 'Student support tickets will appear here after submission.'
                            : 'Try changing the search text, office, status, or priority filter.',
                      )
                    else
                      _AllTicketsTable(
                        tickets: pageTickets,
                        compact: compact,
                        onView: _openTicketDetails,
                      ),
                    if (filtered.isNotEmpty) ...[
                      const SizedBox(height: 14),
                      _AllTicketsPager(
                        page: page,
                        pageCount: pageCount,
                        pageSize: _kAllTicketsPageSize,
                        filteredCount: filtered.length,
                        onPageChanged: (next) => setState(() => _page = next),
                      ),
                    ],
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

class _AllTicketsHeader extends StatelessWidget {
  const _AllTicketsHeader({
    required this.stacked,
    required this.searchCtrl,
    required this.onSearchChanged,
  });

  final bool stacked;
  final TextEditingController searchCtrl;
  final ValueChanged<String> onSearchChanged;

  @override
  Widget build(BuildContext context) {
    final copy = const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'All Tickets',
          style: TextStyle(
            color: DesignTokens.ink,
            fontSize: 28,
            fontWeight: FontWeight.w900,
            height: 1.1,
          ),
        ),
        SizedBox(height: 6),
        Text(
          'Review and manage all student support tickets across offices and statuses.',
          style: TextStyle(
            color: DesignTokens.muted,
            fontSize: 13,
            fontWeight: FontWeight.w600,
            height: 1.35,
          ),
        ),
      ],
    );
    final search = TextField(
      key: const Key('admin-all-tickets-search'),
      controller: searchCtrl,
      onChanged: onSearchChanged,
      decoration: InputDecoration(
        hintText: 'Search tickets, subject, requester, or email...',
        prefixIcon: const Icon(Icons.search_rounded, size: 20),
        suffixIcon: searchCtrl.text.isEmpty
            ? null
            : IconButton(
                onPressed: () {
                  searchCtrl.clear();
                  onSearchChanged('');
                },
                icon: const Icon(Icons.clear_rounded),
              ),
        isDense: true,
        filled: true,
        fillColor: Colors.white,
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: DesignTokens.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: DesignTokens.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: DesignTokens.maroon, width: 1.2),
        ),
      ),
    );
    if (stacked) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          copy,
          const SizedBox(height: 12),
          search,
        ],
      );
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(child: copy),
        const SizedBox(width: 16),
        SizedBox(width: 360, child: search),
      ],
    );
  }
}

class _AllTicketsStatsRow extends StatelessWidget {
  const _AllTicketsStatsRow({
    required this.total,
    required this.open,
    required this.inProgress,
    required this.closed,
  });

  final int total;
  final int open;
  final int inProgress;
  final int closed;

  @override
  Widget build(BuildContext context) {
    final stats = [
      (
        label: 'Total Tickets',
        value: '$total',
        key: 'admin-all-tickets-stat-total',
        background: const Color(0xFFF8EDED),
        valueColor: DesignTokens.maroon,
      ),
      (
        label: 'Open',
        value: '$open',
        key: 'admin-all-tickets-stat-open',
        background: const Color(0xFFFFF4E8),
        valueColor: const Color(0xFFC2410C),
      ),
      (
        label: 'In Progress',
        value: '$inProgress',
        key: 'admin-all-tickets-stat-progress',
        background: const Color(0xFFEFF6FF),
        valueColor: const Color(0xFF1D4ED8),
      ),
      (
        label: 'Closed',
        value: '$closed',
        key: 'admin-all-tickets-stat-closed',
        background: const Color(0xFFECFDF3),
        valueColor: const Color(0xFF15803D),
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
                child: Container(
                  key: Key(stat.key),
                  padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
                  decoration: BoxDecoration(
                    color: stat.background,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: DesignTokens.border),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        stat.value,
                        style: TextStyle(
                          color: stat.valueColor,
                          fontSize: 28,
                          fontWeight: FontWeight.w800,
                          height: 1,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        stat.label,
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
          ],
        );
      },
    );
  }
}

class _AllTicketsFilterBar extends StatelessWidget {
  const _AllTicketsFilterBar({
    required this.officeFilter,
    required this.statusFilter,
    required this.priorityFilter,
    required this.officeOptions,
    required this.stacked,
    required this.onOfficeChanged,
    required this.onStatusChanged,
    required this.onPriorityChanged,
    required this.onReset,
  });

  final String officeFilter;
  final String statusFilter;
  final String priorityFilter;
  final List<String> officeOptions;
  final bool stacked;
  final ValueChanged<String> onOfficeChanged;
  final ValueChanged<String> onStatusChanged;
  final ValueChanged<String> onPriorityChanged;
  final VoidCallback onReset;

  @override
  Widget build(BuildContext context) {
    final officeItems = officeOptions.isEmpty ? const ['All'] : officeOptions;
    final filters = [
      _AllTicketsFilterDropdown(
        fieldKey: const Key('admin-all-tickets-office-filter'),
        label: 'Office',
        value: officeItems.contains(officeFilter) ? officeFilter : 'All',
        values: officeItems,
        displayLabel: (value) => value == 'All' ? 'All Offices' : value,
        onChanged: onOfficeChanged,
      ),
      _AllTicketsFilterDropdown(
        fieldKey: const Key('admin-all-tickets-status-filter'),
        label: 'Status',
        value: statusFilter,
        values: const ['All', 'Open', 'In Progress', 'Resolved', 'Closed'],
        displayLabel: (value) => value == 'All' ? 'All Statuses' : value,
        onChanged: onStatusChanged,
      ),
      _AllTicketsFilterDropdown(
        fieldKey: const Key('admin-all-tickets-priority-filter'),
        label: 'Priority',
        value: priorityFilter,
        values: const ['All', 'Low', 'Medium', 'High', 'Urgent'],
        displayLabel: (value) => value == 'All' ? 'All Priorities' : value,
        onChanged: onPriorityChanged,
      ),
    ];
    final reset = OutlinedButton(
      key: const Key('admin-all-tickets-reset'),
      onPressed: onReset,
      style: OutlinedButton.styleFrom(
        foregroundColor: DesignTokens.maroon,
        side: const BorderSide(color: Color(0xFFD7B4B6)),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
      child: const Text(
        'Reset Filters',
        style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
      ),
    );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: stacked
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                ...filters.map(
                  (filter) => Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: filter,
                  ),
                ),
                Align(alignment: Alignment.centerLeft, child: reset),
              ],
            )
          : Row(
              children: [
                for (var i = 0; i < filters.length; i++) ...[
                  Expanded(child: filters[i]),
                  const SizedBox(width: 12),
                ],
                reset,
              ],
            ),
    );
  }
}

class _AllTicketsFilterDropdown extends StatelessWidget {
  const _AllTicketsFilterDropdown({
    required this.fieldKey,
    required this.label,
    required this.value,
    required this.values,
    required this.displayLabel,
    required this.onChanged,
  });

  final Key fieldKey;

  final String label;
  final String value;
  final List<String> values;
  final String Function(String value) displayLabel;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: DesignTokens.muted,
            fontSize: 11,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 6),
        DropdownButtonFormField<String>(
          key: fieldKey,
          value: values.contains(value) ? value : values.first,
          isExpanded: true,
          decoration: InputDecoration(
            isDense: true,
            filled: true,
            fillColor: Colors.white,
            contentPadding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: DesignTokens.border),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: DesignTokens.border),
            ),
          ),
          items: values
              .map(
                (item) => DropdownMenuItem(
                  value: item,
                  child: Text(
                    displayLabel(item),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              )
              .toList(),
          onChanged: (next) {
            if (next != null) onChanged(next);
          },
        ),
      ],
    );
  }
}

class _AllTicketsEmpty extends StatelessWidget {
  const _AllTicketsEmpty({
    required this.title,
    required this.message,
  });

  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
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
            key: const Key('admin-all-tickets-empty'),
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

class _AllTicketsTable extends StatelessWidget {
  const _AllTicketsTable({
    required this.tickets,
    required this.compact,
    required this.onView,
  });

  final List<_AdminTicketEntry> tickets;
  final bool compact;
  final ValueChanged<_AdminTicketEntry> onView;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        children: [
          if (!compact) const _AllTicketsTableHeader(),
          for (var i = 0; i < tickets.length; i++) ...[
            if (i > 0 || !compact)
              const Divider(height: 1, color: DesignTokens.border),
            compact
                ? _AllTicketsCardRow(
                    ticket: tickets[i],
                    onView: () => onView(tickets[i]),
                  )
                : _AllTicketsTableRow(
                    ticket: tickets[i],
                    onView: () => onView(tickets[i]),
                  ),
          ],
        ],
      ),
    );
  }
}

class _AllTicketsTableHeader extends StatelessWidget {
  const _AllTicketsTableHeader();

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
          Expanded(flex: 4, child: Text('SUBJECT', style: style)),
          Expanded(flex: 2, child: Text('OFFICE', style: style)),
          Expanded(flex: 2, child: Text('REQUESTER', style: style)),
          SizedBox(width: 108, child: Text('STATUS', style: style)),
          SizedBox(width: 88, child: Text('PRIORITY', style: style)),
          SizedBox(width: 92, child: Text('CREATED AT', style: style)),
          SizedBox(
            width: 56,
            child: Text('ACTIONS', style: style, textAlign: TextAlign.right),
          ),
        ],
      ),
    );
  }
}

class _AllTicketsTableRow extends StatelessWidget {
  const _AllTicketsTableRow({
    required this.ticket,
    required this.onView,
  });

  final _AdminTicketEntry ticket;
  final VoidCallback onView;

  @override
  Widget build(BuildContext context) {
    final requester = _allTicketsRequester(ticket);
    return Padding(
      key: Key('admin-all-tickets-row-${ticket.id}'),
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
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
            flex: 4,
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
            flex: 2,
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
            child: Tooltip(
              message: [
                ticket.userName,
                if ((ticket.userEmail ?? '').isNotEmpty) ticket.userEmail!,
              ].join('\n'),
              child: Text(
                requester,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w600,
                  fontSize: 13,
                ),
              ),
            ),
          ),
          SizedBox(
            width: 108,
            child: Align(
              alignment: Alignment.centerLeft,
              child: _AllTicketsStatusPill(status: ticket.status),
            ),
          ),
          SizedBox(
            width: 88,
            child: Align(
              alignment: Alignment.centerLeft,
              child: _AllTicketsPriorityPill(priority: ticket.priority),
            ),
          ),
          SizedBox(
            width: 92,
            child: _AllTicketsCreatedAt(date: ticket.createdAt),
          ),
          SizedBox(
            width: 56,
            child: Align(
              alignment: Alignment.centerRight,
              child: _AllTicketsViewLink(
                key: Key('admin-all-tickets-view-${ticket.id}'),
                onTap: onView,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AllTicketsCardRow extends StatelessWidget {
  const _AllTicketsCardRow({
    required this.ticket,
    required this.onView,
  });

  final _AdminTicketEntry ticket;
  final VoidCallback onView;

  @override
  Widget build(BuildContext context) {
    return Padding(
      key: Key('admin-all-tickets-row-${ticket.id}'),
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
            [
              ticket.assignedOffice,
              _allTicketsRequester(ticket),
            ].join(' · '),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              _AllTicketsStatusPill(status: ticket.status),
              _AllTicketsPriorityPill(priority: ticket.priority),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            _allTicketsCreatedLabel(ticket.createdAt),
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          _AllTicketsViewLink(
            key: Key('admin-all-tickets-view-${ticket.id}'),
            onTap: onView,
          ),
        ],
      ),
    );
  }
}

class _AllTicketsCreatedAt extends StatelessWidget {
  const _AllTicketsCreatedAt({required this.date});

  final DateTime date;

  @override
  Widget build(BuildContext context) {
    final local = date.toLocal();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${_adminFormatDate(local)}, ${local.year}',
          style: const TextStyle(
            color: DesignTokens.ink,
            fontSize: 12,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          _officeDashboardTimeLine(local),
          style: const TextStyle(
            color: DesignTokens.muted,
            fontSize: 11,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _AllTicketsViewLink extends StatelessWidget {
  const _AllTicketsViewLink({
    super.key,
    required this.onTap,
  });

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(6),
      child: const Padding(
        padding: EdgeInsets.symmetric(horizontal: 4, vertical: 4),
        child: Text(
          'View',
          style: TextStyle(
            color: DesignTokens.ink,
            fontWeight: FontWeight.w800,
            fontSize: 13,
          ),
        ),
      ),
    );
  }
}

class _AllTicketsStatusPill extends StatelessWidget {
  const _AllTicketsStatusPill({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final colors = switch (status) {
      'Open' => (const Color(0xFFFEE2E2), const Color(0xFFB91C1C)),
      'In Progress' => (const Color(0xFFDBEAFE), const Color(0xFF1D4ED8)),
      'Closed' => (const Color(0xFFDCFCE7), const Color(0xFF15803D)),
      'Resolved' => (const Color(0xFFD1FAE5), const Color(0xFF047857)),
      _ => (const Color(0xFFF1F5F9), DesignTokens.muted),
    };
    return _AllTicketsPill(label: status, background: colors.$1, foreground: colors.$2);
  }
}

class _AllTicketsPriorityPill extends StatelessWidget {
  const _AllTicketsPriorityPill({required this.priority});

  final String priority;

  @override
  Widget build(BuildContext context) {
    final colors = switch (priority) {
      'Low' => (const Color(0xFFDCFCE7), const Color(0xFF15803D)),
      'Medium' => (const Color(0xFFFEF3C7), const Color(0xFFB45309)),
      'High' => (const Color(0xFFFEE2E2), const Color(0xFFB91C1C)),
      'Urgent' => (const Color(0xFFFECACA), const Color(0xFF991B1B)),
      _ => (const Color(0xFFF1F5F9), DesignTokens.muted),
    };
    return _AllTicketsPill(
      label: priority,
      background: colors.$1,
      foreground: colors.$2,
    );
  }
}

class _AllTicketsPill extends StatelessWidget {
  const _AllTicketsPill({
    required this.label,
    required this.background,
    required this.foreground,
  });

  final String label;
  final Color background;
  final Color foreground;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          color: foreground,
          fontSize: 11,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _AllTicketsPager extends StatelessWidget {
  const _AllTicketsPager({
    required this.page,
    required this.pageCount,
    required this.pageSize,
    required this.filteredCount,
    required this.onPageChanged,
  });

  final int page;
  final int pageCount;
  final int pageSize;
  final int filteredCount;
  final ValueChanged<int> onPageChanged;

  @override
  Widget build(BuildContext context) {
    final start = filteredCount == 0 ? 0 : ((page - 1) * pageSize) + 1;
    final end = (page * pageSize).clamp(0, filteredCount);
    final pages = _visiblePages(page, pageCount);
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 720;
        return Wrap(
          key: const Key('admin-all-tickets-pager'),
          spacing: 4,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          alignment: compact ? WrapAlignment.start : WrapAlignment.spaceBetween,
          children: [
            Text(
              'Showing $start–$end of $filteredCount tickets',
              style: const TextStyle(
                color: DesignTokens.muted,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
            Wrap(
              spacing: 2,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                TextButton(
                  onPressed: page > 1 ? () => onPageChanged(page - 1) : null,
                  style: TextButton.styleFrom(
                    minimumSize: Size.zero,
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: const Text('Previous'),
                ),
                for (final item in pages)
                  item == null
                      ? const Padding(
                          padding: EdgeInsets.symmetric(horizontal: 6),
                          child: Text(
                            '…',
                            style: TextStyle(
                              color: DesignTokens.muted,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        )
                      : Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 2),
                          child: Material(
                            color: item == page
                                ? DesignTokens.maroon
                                : Colors.white,
                            borderRadius: BorderRadius.circular(8),
                            child: InkWell(
                              onTap: () => onPageChanged(item),
                              borderRadius: BorderRadius.circular(8),
                              child: Container(
                                width: 32,
                                height: 32,
                                alignment: Alignment.center,
                                decoration: BoxDecoration(
                                  borderRadius: BorderRadius.circular(8),
                                  border: Border.all(
                                    color: item == page
                                        ? DesignTokens.maroon
                                        : DesignTokens.border,
                                  ),
                                ),
                                child: Text(
                                  '$item',
                                  style: TextStyle(
                                    color: item == page
                                        ? Colors.white
                                        : DesignTokens.ink,
                                    fontWeight: FontWeight.w800,
                                    fontSize: 12,
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                TextButton(
                  onPressed:
                      page < pageCount ? () => onPageChanged(page + 1) : null,
                  style: TextButton.styleFrom(
                    minimumSize: Size.zero,
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: const Text('Next'),
                ),
              ],
            ),
          ],
        );
      },
    );
  }

  List<int?> _visiblePages(int current, int total) {
    if (total <= 7) return [for (var i = 1; i <= total; i++) i];
    if (current <= 3) {
      return [1, 2, 3, null, total];
    }
    if (current >= total - 2) {
      return [1, null, total - 2, total - 1, total];
    }
    return [1, null, current - 1, current, current + 1, null, total];
  }
}

String _allTicketsRequester(_AdminTicketEntry ticket) {
  final email = (ticket.userEmail ?? '').trim();
  if (email.isNotEmpty) return email;
  return ticket.userName;
}

String _allTicketsCreatedLabel(DateTime date) {
  final local = date.toLocal();
  return '${_adminFormatDate(local)}, ${local.year} ${_officeDashboardTimeLine(local)}';
}
