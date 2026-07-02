import 'dart:convert';
import 'dart:html' as html;

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../widgets/sidebar.dart';
import '../widgets/student_ui.dart';
import 'login_page.dart';

class AdminDashboardPage extends StatefulWidget {
  const AdminDashboardPage({super.key});

  @override
  State<AdminDashboardPage> createState() => _AdminDashboardPageState();
}

class _AdminDashboardPageState extends State<AdminDashboardPage> {
  _TicketStats? _stats;
  bool _loading = false;
  String? _error;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    if (auth.role == 'admin' && !_loading && _stats == null && _error == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _loadStats();
      });
    }
  }

  Future<void> _loadStats() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      _stats = await _loadTicketStats(context);
    } catch (error) {
      _error = _friendlyError(error);
    } finally {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final stats = _stats;
    final cards = [
      _AdminMetricData('Total Tickets', stats?.totalText ?? '-',
          Icons.confirmation_number_rounded),
      _AdminMetricData('Open Tickets', stats?.openText ?? '-',
          Icons.mark_email_unread_rounded,
          statusFilter: 'Open'),
      _AdminMetricData('In Progress', stats?.inProgressText ?? '-',
          Icons.timelapse_rounded,
          statusFilter: 'In Progress'),
      _AdminMetricData('Closed', stats?.closedText ?? '-',
          Icons.check_circle_rounded,
          statusFilter: 'Closed'),
      const _AdminMetricData(
          'High Priority', '-', Icons.priority_high_rounded),
      _AdminMetricData(
          'Offices', stats?.officeCountText ?? '-', Icons.apartment_rounded),
    ];

    return AdminScaffold(
      current: StudentNavItem.adminDashboard,
      title: 'Admin Dashboard',
      description:
          'Monitor support volume, ticket status, and administrative workload.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_loading) const LinearProgressIndicator(minHeight: 3),
          if (_error != null)
            _AdminNotice(
              icon: Icons.info_outline_rounded,
              message: 'Ticket statistics are not available yet. $_error',
            ),
          LayoutBuilder(
            builder: (context, constraints) {
              final columns = constraints.maxWidth >= 900
                  ? 3
                  : constraints.maxWidth >= 560
                      ? 2
                      : 1;
              return StudentResponsiveWrap(
                columns: columns,
                spacing: 14,
                children: cards
                    .map((card) => _AdminMetricCard(
                          data: card,
                          onTap: () => Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => AdminAllTicketsPage(
                                initialStatusFilter:
                                    card.statusFilter ?? 'All',
                              ),
                            ),
                          ),
                        ))
                    .toList(),
              );
            },
          ),
          const SizedBox(height: 18),
          const _AdminNotice(
            icon: Icons.admin_panel_settings_rounded,
            message:
                'Full administrative workflows are being prepared. Use the existing knowledge-base Admin Panel for document ingest and retrieval testing.',
          ),
        ],
      ),
    );
  }
}

class AdminAllTicketsPage extends StatefulWidget {
  final String initialStatusFilter;

  const AdminAllTicketsPage({super.key, this.initialStatusFilter = 'All'});

  @override
  State<AdminAllTicketsPage> createState() => _AdminAllTicketsPageState();
}

class _AdminAllTicketsPageState extends State<AdminAllTicketsPage> {
  final List<_AdminTicketEntry> _tickets = [];
  final TextEditingController _searchCtrl = TextEditingController();
  bool _loading = false;
  String? _error;
  late String _statusFilter;
  String _priorityFilter = 'All';
  String _officeFilter = 'All';
  bool _requestedInitialLoad = false;

  @override
  void initState() {
    super.initState();
    _statusFilter = widget.initialStatusFilter;
    _searchCtrl.addListener(() => setState(() {}));
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    if (auth.role == 'admin' && !_requestedInitialLoad) {
      _requestedInitialLoad = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _loadTickets();
      });
    }
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadTickets() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final request = html.HttpRequest();
      request.open('GET', '${AppConfig.resolvedApiBase}/tickets');
      AuthScope.of(context).ticketHeaders().forEach(request.setRequestHeader);
      request.send();
      await request.onLoadEnd.first;
      final data = _decodeObject(request.responseText);
      final statusCode = request.status ?? 0;
      if (statusCode < 200 || statusCode >= 300) {
        throw StateError(_extractError(data, 'Could not load tickets.'));
      }
      final items = data['items'] is List ? data['items'] as List : const [];
      setState(() {
        _tickets
          ..clear()
          ..addAll(items.whereType<Map>().map((item) =>
              _AdminTicketEntry.fromJson(Map<String, dynamic>.from(item))));
      });
    } catch (error) {
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
  }

  Future<_AdminTicketEntry> _patchTicket(
    _AdminTicketEntry ticket,
    Map<String, dynamic> payload,
  ) async {
    final request = html.HttpRequest();
    request.open('PATCH', '${AppConfig.resolvedApiBase}/tickets/${ticket.id}');
    AuthScope.of(context).ticketHeaders().forEach(request.setRequestHeader);
    request.setRequestHeader('Content-Type', 'application/json');
    request.send(jsonEncode(payload));
    await request.onLoadEnd.first;
    final data = _decodeObject(request.responseText);
    final statusCode = request.status ?? 0;
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
    final request = html.HttpRequest();
    request.open(
        'POST', '${AppConfig.resolvedApiBase}/tickets/${ticket.id}/replies');
    AuthScope.of(context).ticketHeaders().forEach(request.setRequestHeader);
    request.setRequestHeader('Content-Type', 'application/json');
    request.send(jsonEncode({'message': message}));
    await request.onLoadEnd.first;
    final data = _decodeObject(request.responseText);
    final statusCode = request.status ?? 0;
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

  @override
  Widget build(BuildContext context) {
    final filteredTickets = _tickets
        .where((ticket) => ticket.matches(
              _searchCtrl.text,
              _statusFilter,
              _priorityFilter,
              _officeFilter,
            ))
        .toList();

    return AdminScaffold(
      current: StudentNavItem.adminAllTickets,
      title: 'All Tickets',
      description:
          'Review all student support tickets across offices and statuses.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_loading) const LinearProgressIndicator(minHeight: 3),
          if (_error != null)
            _AdminNotice(
              icon: Icons.info_outline_rounded,
              message: _error!,
            ),
          _AdminTicketSummary(tickets: _tickets),
          const SizedBox(height: 16),
          _AdminTicketFilters(
            searchCtrl: _searchCtrl,
            statusFilter: _statusFilter,
            priorityFilter: _priorityFilter,
            officeFilter: _officeFilter,
            officeOptions: _officeOptions(),
            onStatusChanged: (value) => setState(() => _statusFilter = value),
            onPriorityChanged: (value) =>
                setState(() => _priorityFilter = value),
            onOfficeChanged: (value) => setState(() => _officeFilter = value),
            onRefresh: _loadTickets,
            isRefreshing: _loading,
          ),
          const SizedBox(height: 16),
          if (_loading && _tickets.isEmpty)
            const _AdminTicketState(
              icon: Icons.sync_rounded,
              title: 'Loading tickets',
              message: 'Fetching the admin ticket queue.',
            )
          else
            _AdminTicketList(
              tickets: filteredTickets,
              hasAnyTickets: _tickets.isNotEmpty,
              onTicketTap: _openTicketDetails,
            ),
        ],
      ),
    );
  }

  List<String> _officeOptions({bool includeAll = true}) {
    final values = _tickets
        .map((ticket) => ticket.assignedOffice)
        .where((value) => value.trim().isNotEmpty)
        .toSet()
        .toList()
      ..sort();
    return [if (includeAll) 'All', ...values];
  }
}

class AdminUsersRolesPage extends StatelessWidget {
  const AdminUsersRolesPage({super.key});

  @override
  Widget build(BuildContext context) {
    return const AdminPlaceholderPage(
      current: StudentNavItem.adminUsersRoles,
      title: 'Users & Roles',
      description:
          'Manage student, office, and admin access when user-management endpoints are ready.',
      icon: Icons.manage_accounts_rounded,
    );
  }
}

class AdminOfficesPage extends StatelessWidget {
  const AdminOfficesPage({super.key});

  @override
  Widget build(BuildContext context) {
    return const AdminPlaceholderPage(
      current: StudentNavItem.adminOffices,
      title: 'Offices',
      description:
          'Maintain routing offices, staff assignments, and service ownership.',
      icon: Icons.apartment_rounded,
    );
  }
}

class AdminReportsPage extends StatefulWidget {
  const AdminReportsPage({super.key});

  @override
  State<AdminReportsPage> createState() => _AdminReportsPageState();
}

class _AdminReportsPageState extends State<AdminReportsPage> {
  _TicketStats? _stats;
  bool _loading = false;
  String? _error;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    if (auth.role == 'admin' && !_loading && _stats == null && _error == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _loadStats();
      });
    }
  }

  Future<void> _loadStats() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      _stats = await _loadTicketStats(context);
    } catch (error) {
      _error = _friendlyError(error);
    } finally {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final stats = _stats;
    return AdminScaffold(
      current: StudentNavItem.adminReports,
      title: 'Reports / Statistics',
      description:
          'Track ticket volume and office workload for administrative review.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_loading) const LinearProgressIndicator(minHeight: 3),
          _AdminPlaceholderPanel(
            icon: Icons.query_stats_rounded,
            title: stats == null ? 'Reports coming soon' : 'Ticket statistics',
            description: stats == null
                ? 'This page will use GET /tickets/statistics for admin reporting once the dashboard data is available.'
                : 'Total: ${stats.totalText} | Open: ${stats.openText} | In progress: ${stats.inProgressText} | Closed: ${stats.closedText}',
          ),
          if (_error != null)
            _AdminNotice(
              icon: Icons.info_outline_rounded,
              message: _error!,
            ),
        ],
      ),
    );
  }
}

class AdminPlaceholderPage extends StatelessWidget {
  final StudentNavItem current;
  final String title;
  final String description;
  final IconData icon;

  const AdminPlaceholderPage({
    super.key,
    required this.current,
    required this.title,
    required this.description,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return AdminScaffold(
      current: current,
      title: title,
      description: description,
      child: _AdminPlaceholderPanel(
        icon: icon,
        title: 'Coming soon',
        description: description,
      ),
    );
  }
}

class AdminScaffold extends StatelessWidget {
  final StudentNavItem current;
  final String title;
  final String description;
  final Widget child;

  const AdminScaffold({
    super.key,
    required this.current,
    required this.title,
    required this.description,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    if (auth.role != 'admin') {
      return Scaffold(
        backgroundColor: DesignTokens.bgGrey,
        appBar: AppBar(title: Text(title)),
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: StudentPanel(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const StudentIconBox(
                    icon: Icons.admin_panel_settings_rounded,
                    color: DesignTokens.maroon,
                    size: 52,
                  ),
                  const SizedBox(height: 14),
                  const StudentSectionTitle(
                    title: 'Admin access required',
                    subtitle:
                        'Please log in with an admin account to open this page.',
                  ),
                  const SizedBox(height: 16),
                  ElevatedButton.icon(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => LoginPage(
                          returnTo: (_) => this,
                          message:
                              'Please log in with an admin account to open admin tools.',
                        ),
                      ),
                    ),
                    icon: const Icon(Icons.login_rounded, size: 18),
                    label: const Text('Login'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 900;
        final content = StudentPage(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              StudentPanel(
                child: Row(
                  children: [
                    const StudentIconBox(
                      icon: Icons.admin_panel_settings_rounded,
                      color: DesignTokens.maroon,
                      size: 52,
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: StudentSectionTitle(
                        title: title,
                        subtitle: description,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              child,
            ],
          ),
        );

        if (isWide) {
          return Scaffold(
            backgroundColor: DesignTokens.bgGrey,
            body: Row(
              children: [
                SizedBox(width: 220, child: AppSidebar(current: current)),
                Expanded(child: content),
              ],
            ),
          );
        }

        return Scaffold(
          backgroundColor: DesignTokens.bgGrey,
          drawer: Drawer(child: AppSidebar(current: current)),
          appBar: AppBar(title: Text(title)),
          body: content,
        );
      },
    );
  }
}

class _AdminMetricCard extends StatelessWidget {
  final _AdminMetricData data;
  final VoidCallback? onTap;

  const _AdminMetricCard({required this.data, this.onTap});

  @override
  Widget build(BuildContext context) {
    return StudentInkCard(
      onTap: onTap,
      child: Row(
        children: [
          StudentIconBox(icon: data.icon, color: DesignTokens.maroon, size: 44),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  data.value,
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontSize: 24,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  data.label,
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ),
          ),
          if (onTap != null)
            const Icon(Icons.chevron_right_rounded, color: DesignTokens.muted),
        ],
      ),
    );
  }
}

class _AdminTicketSummary extends StatelessWidget {
  final List<_AdminTicketEntry> tickets;

  const _AdminTicketSummary({required this.tickets});

  @override
  Widget build(BuildContext context) {
    final open = tickets.where((ticket) => ticket.status == 'Open').length;
    final progress =
        tickets.where((ticket) => ticket.status == 'In Progress').length;
    final closed = tickets.where((ticket) => ticket.status == 'Closed').length;
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 860
            ? 4
            : constraints.maxWidth >= 560
                ? 2
                : 1;
        return StudentResponsiveWrap(
          columns: columns,
          spacing: 14,
          children: [
            _AdminMiniStat(
                label: 'Total', value: '${tickets.length}', icon: Icons.list_alt_rounded),
            _AdminMiniStat(
                label: 'Open', value: '$open', icon: Icons.mark_email_unread_rounded),
            _AdminMiniStat(
                label: 'In Progress', value: '$progress', icon: Icons.sync_rounded),
            _AdminMiniStat(
                label: 'Closed', value: '$closed', icon: Icons.check_circle_rounded),
          ],
        );
      },
    );
  }
}

class _AdminMiniStat extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;

  const _AdminMiniStat({
    required this.label,
    required this.value,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      padding: const EdgeInsets.all(15),
      child: Row(
        children: [
          StudentIconBox(icon: icon, color: DesignTokens.maroon, size: 38),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  value,
                  style: const TextStyle(
                    color: DesignTokens.maroon,
                    fontWeight: FontWeight.w900,
                    fontSize: 22,
                    height: 1,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  label,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontWeight: FontWeight.w800,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AdminTicketFilters extends StatelessWidget {
  final TextEditingController searchCtrl;
  final String statusFilter;
  final String priorityFilter;
  final String officeFilter;
  final List<String> officeOptions;
  final ValueChanged<String> onStatusChanged;
  final ValueChanged<String> onPriorityChanged;
  final ValueChanged<String> onOfficeChanged;
  final Future<void> Function() onRefresh;
  final bool isRefreshing;

  const _AdminTicketFilters({
    required this.searchCtrl,
    required this.statusFilter,
    required this.priorityFilter,
    required this.officeFilter,
    required this.officeOptions,
    required this.onStatusChanged,
    required this.onPriorityChanged,
    required this.onOfficeChanged,
    required this.onRefresh,
    required this.isRefreshing,
  });

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      padding: const EdgeInsets.all(16),
      shadow: false,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 820;
          final search = TextField(
            controller: searchCtrl,
            decoration: _adminInputDecoration(
              hintText: 'Search ID, subject, office, category, name, or email',
              icon: Icons.search_rounded,
            ),
          );
          final filters = [
            _AdminFilterDropdown(
              label: 'Status',
              value: statusFilter,
              values: const ['All', 'Open', 'In Progress', 'Resolved', 'Closed'],
              icon: Icons.tune_rounded,
              onChanged: onStatusChanged,
            ),
            _AdminFilterDropdown(
              label: 'Priority',
              value: priorityFilter,
              values: const ['All', 'Low', 'Medium', 'High', 'Urgent'],
              icon: Icons.priority_high_rounded,
              onChanged: onPriorityChanged,
            ),
            _AdminFilterDropdown(
              label: 'Office',
              value: officeOptions.contains(officeFilter) ? officeFilter : 'All',
              values: officeOptions.isEmpty ? const ['All'] : officeOptions,
              icon: Icons.apartment_rounded,
              onChanged: onOfficeChanged,
            ),
          ];

          final refresh = Tooltip(
            message: 'Refresh tickets',
            child: IconButton(
              color: DesignTokens.maroon,
              onPressed: isRefreshing ? null : () => onRefresh(),
              icon: isRefreshing
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh_rounded),
            ),
          );

          if (compact) {
            return Column(
              children: [
                search,
                const SizedBox(height: 12),
                ...filters.map((filter) => Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: filter,
                    )),
                Align(alignment: Alignment.centerRight, child: refresh),
              ],
            );
          }

          return Row(
            children: [
              Expanded(flex: 3, child: search),
              const SizedBox(width: 12),
              ...filters
                  .map((filter) => Expanded(child: Padding(
                        padding: const EdgeInsets.only(right: 12),
                        child: filter,
                      )))
                  .toList(),
              refresh,
            ],
          );
        },
      ),
    );
  }
}

class _AdminFilterDropdown extends StatelessWidget {
  final String label;
  final String value;
  final List<String> values;
  final IconData icon;
  final ValueChanged<String> onChanged;

  const _AdminFilterDropdown({
    required this.label,
    required this.value,
    required this.values,
    required this.icon,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<String>(
      value: values.contains(value) ? value : values.first,
      isExpanded: true,
      decoration: _adminInputDecoration(hintText: label, icon: icon),
      items: values
          .map((item) => DropdownMenuItem(value: item, child: Text(item)))
          .toList(),
      onChanged: (value) {
        if (value != null) onChanged(value);
      },
    );
  }
}

class _AdminTicketList extends StatelessWidget {
  final List<_AdminTicketEntry> tickets;
  final bool hasAnyTickets;
  final ValueChanged<_AdminTicketEntry> onTicketTap;

  const _AdminTicketList({
    required this.tickets,
    required this.hasAnyTickets,
    required this.onTicketTap,
  });

  @override
  Widget build(BuildContext context) {
    if (tickets.isEmpty) {
      return _AdminTicketState(
        icon: hasAnyTickets ? Icons.manage_search_rounded : Icons.inbox_outlined,
        title: hasAnyTickets ? 'No matching tickets' : 'No tickets yet',
        message: hasAnyTickets
            ? 'Try changing the search text, status, priority, or office filter.'
            : 'Student support tickets will appear here after submission.',
      );
    }

    return Column(
      children: tickets
          .map((ticket) => Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: _AdminTicketCard(
                  ticket: ticket,
                  onTap: () => onTicketTap(ticket),
                ),
              ))
          .toList(),
    );
  }
}

class _AdminTicketCard extends StatelessWidget {
  final _AdminTicketEntry ticket;
  final VoidCallback onTap;

  const _AdminTicketCard({required this.ticket, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return StudentInkCard(
      onTap: onTap,
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(
                          ticket.id,
                          style: const TextStyle(
                            color: DesignTokens.maroon,
                            fontWeight: FontWeight.w900,
                            fontSize: 13,
                          ),
                        ),
                        _AdminStatusChip(status: ticket.status),
                        _AdminPriorityChip(priority: ticket.priority),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Text(
                      ticket.subject,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: DesignTokens.ink,
                        fontWeight: FontWeight.w900,
                        fontSize: 17,
                        height: 1.25,
                      ),
                    ),
                    if (ticket.description.trim().isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text(
                        ticket.description,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: DesignTokens.muted,
                          height: 1.35,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 10),
              const Icon(Icons.chevron_right_rounded,
                  color: DesignTokens.muted),
            ],
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              _AdminMetaItem(
                  icon: Icons.person_outline_rounded, label: ticket.userName),
              _AdminMetaItem(
                  icon: Icons.apartment_rounded,
                  label: ticket.assignedOffice),
              _AdminMetaItem(
                  icon: Icons.category_outlined, label: ticket.category),
              _AdminMetaItem(
                  icon: Icons.event_available_outlined,
                  label: 'Created ${_adminFormatDate(ticket.createdAt)}'),
              _AdminMetaItem(
                  icon: Icons.update_rounded,
                  label: 'Updated ${_adminFormatDate(ticket.updatedAt)}'),
              _AdminMetaItem(
                  icon: Icons.forum_outlined,
                  label: '${ticket.messages.length} replies'),
            ],
          ),
        ],
      ),
    );
  }
}

class _AdminTicketState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String message;

  const _AdminTicketState({
    required this.icon,
    required this.title,
    required this.message,
  });

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      padding: const EdgeInsets.all(24),
      child: Column(
        children: [
          StudentIconBox(icon: icon, color: DesignTokens.maroon, size: 52),
          const SizedBox(height: 12),
          Text(
            title,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w900,
              fontSize: 18,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: DesignTokens.muted, height: 1.4),
          ),
        ],
      ),
    );
  }
}

class _AdminTicketDetailsDialog extends StatefulWidget {
  final _AdminTicketEntry ticket;
  final List<String> offices;
  final Future<_AdminTicketEntry> Function(Map<String, dynamic> payload)
      onUpdate;
  final Future<_AdminTicketEntry> Function(String message) onReply;

  const _AdminTicketDetailsDialog({
    required this.ticket,
    required this.offices,
    required this.onUpdate,
    required this.onReply,
  });

  @override
  State<_AdminTicketDetailsDialog> createState() =>
      _AdminTicketDetailsDialogState();
}

class _AdminTicketDetailsDialogState extends State<_AdminTicketDetailsDialog> {
  late _AdminTicketEntry _ticket;
  late String _status;
  late String _priority;
  late String _office;
  final TextEditingController _categoryCtrl = TextEditingController();
  final TextEditingController _replyCtrl = TextEditingController();
  String? _error;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _ticket = widget.ticket;
    _status = _ticket.status;
    _priority = _ticket.priority;
    _office = _ticket.assignedOffice;
    _categoryCtrl.text = _ticket.category;
  }

  @override
  void dispose() {
    _categoryCtrl.dispose();
    _replyCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final offices = _mergeOption(widget.offices, _office);
    final priorities = _mergeOption(const ['Low', 'Medium', 'High'], _priority);
    final statuses =
        _mergeOption(const ['Open', 'In Progress', 'Resolved', 'Closed'], _status);

    return Dialog(
      insetPadding: const EdgeInsets.all(18),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 900, maxHeight: 760),
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(22, 18, 14, 14),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const StudentIconBox(
                    icon: Icons.confirmation_num_outlined,
                    color: DesignTokens.maroon,
                    size: 42,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _ticket.id,
                          style: const TextStyle(
                            color: DesignTokens.maroon,
                            fontWeight: FontWeight.w900,
                            fontSize: 13,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          _ticket.subject,
                          style: const TextStyle(
                            color: DesignTokens.ink,
                            fontWeight: FontWeight.w900,
                            fontSize: 20,
                            height: 1.25,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: 'Close',
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(22),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        _AdminStatusChip(status: _ticket.status),
                        _AdminPriorityChip(priority: _ticket.priority),
                      ],
                    ),
                    const SizedBox(height: 18),
                    _AdminDetailGrid(ticket: _ticket),
                    const SizedBox(height: 20),
                    _AdminSectionTitle('Admin controls'),
                    const SizedBox(height: 10),
                    StudentPanel(
                      shadow: false,
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        children: [
                          LayoutBuilder(
                            builder: (context, constraints) {
                              final compact = constraints.maxWidth < 680;
                              final fields = [
                                _AdminFilterDropdown(
                                  label: 'Status',
                                  value: _status,
                                  values: statuses,
                                  icon: Icons.tune_rounded,
                                  onChanged: (value) =>
                                      setState(() => _status = value),
                                ),
                                _AdminFilterDropdown(
                                  label: 'Priority',
                                  value: _priority,
                                  values: priorities,
                                  icon: Icons.priority_high_rounded,
                                  onChanged: (value) =>
                                      setState(() => _priority = value),
                                ),
                                _AdminFilterDropdown(
                                  label: 'Assigned office',
                                  value: _office,
                                  values: offices,
                                  icon: Icons.apartment_rounded,
                                  onChanged: (value) =>
                                      setState(() => _office = value),
                                ),
                                TextField(
                                  controller: _categoryCtrl,
                                  decoration: _adminInputDecoration(
                                    hintText: 'Category',
                                    icon: Icons.category_outlined,
                                  ),
                                ),
                              ];
                              if (compact) {
                                return Column(
                                  children: fields
                                      .map((field) => Padding(
                                            padding: const EdgeInsets.only(
                                                bottom: 10),
                                            child: field,
                                          ))
                                      .toList(),
                                );
                              }
                              return StudentResponsiveWrap(
                                columns: 2,
                                spacing: 12,
                                children: fields,
                              );
                            },
                          ),
                          const SizedBox(height: 12),
                          Align(
                            alignment: Alignment.centerRight,
                            child: ElevatedButton.icon(
                              onPressed: _saving ? null : _saveChanges,
                              icon: _saving
                                  ? const SizedBox(
                                      width: 16,
                                      height: 16,
                                      child: CircularProgressIndicator(
                                          strokeWidth: 2),
                                    )
                                  : const Icon(Icons.save_rounded, size: 18),
                              label: const Text('Save changes'),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: DesignTokens.maroon,
                                foregroundColor: Colors.white,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      _AdminNotice(
                        icon: Icons.error_outline_rounded,
                        message: _error!,
                      ),
                    ],
                    const SizedBox(height: 20),
                    _AdminSectionTitle('Description'),
                    const SizedBox(height: 8),
                    _AdminTextPanel(
                      text: _ticket.description.trim().isEmpty
                          ? 'No additional description provided.'
                          : _ticket.description,
                    ),
                    const SizedBox(height: 22),
                    _AdminSectionTitle('Conversation'),
                    const SizedBox(height: 12),
                    _AdminConversationTimeline(messages: _ticket.messages),
                    const SizedBox(height: 16),
                    _AdminSectionTitle('Reply'),
                    const SizedBox(height: 8),
                    TextField(
                      controller: _replyCtrl,
                      minLines: 3,
                      maxLines: 5,
                      decoration: _adminInputDecoration(
                        hintText: 'Write an admin reply',
                        icon: Icons.reply_rounded,
                      ),
                    ),
                    const SizedBox(height: 10),
                    Align(
                      alignment: Alignment.centerRight,
                      child: ElevatedButton.icon(
                        onPressed: _saving ? null : _sendReply,
                        icon: const Icon(Icons.send_rounded, size: 18),
                        label: const Text('Send reply'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: DesignTokens.maroon,
                          foregroundColor: Colors.white,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _saveChanges() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final updated = await widget.onUpdate({
        'status': _status,
        'priority': _priority,
        'assigned_office': _office,
        'category': _categoryCtrl.text.trim(),
      });
      setState(() {
        _ticket = updated;
        _status = updated.status;
        _priority = updated.priority;
        _office = updated.assignedOffice;
        _categoryCtrl.text = updated.category;
      });
    } catch (error) {
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _sendReply() async {
    final message = _replyCtrl.text.trim();
    if (message.isEmpty) {
      setState(() => _error = 'Write a reply before sending.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final updated = await widget.onReply(message);
      setState(() {
        _ticket = updated;
        _replyCtrl.clear();
      });
    } catch (error) {
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }
}

class _AdminDetailGrid extends StatelessWidget {
  final _AdminTicketEntry ticket;

  const _AdminDetailGrid({required this.ticket});

  @override
  Widget build(BuildContext context) {
    final details = [
      _AdminDetailData('Student', ticket.userName, Icons.person_outline_rounded),
      _AdminDetailData('Email', ticket.userEmail ?? '-', Icons.email_outlined),
      _AdminDetailData('Category', ticket.category, Icons.category_outlined),
      _AdminDetailData(
          'Assigned office', ticket.assignedOffice, Icons.apartment_rounded),
      _AdminDetailData('Created', _adminFormatFullDate(ticket.createdAt),
          Icons.event_available_outlined),
      _AdminDetailData(
          'Updated', _adminFormatFullDate(ticket.updatedAt), Icons.update_rounded),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 680 ? 2 : 1;
        return StudentResponsiveWrap(
          columns: columns,
          spacing: 12,
          children: details
              .map((detail) => Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(color: DesignTokens.border),
                    ),
                    child: Row(
                      children: [
                        StudentIconBox(
                          icon: detail.icon,
                          color: DesignTokens.maroon,
                          size: 34,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                detail.label,
                                style: const TextStyle(
                                  color: DesignTokens.muted,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              const SizedBox(height: 3),
                              Text(
                                detail.value,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  color: DesignTokens.ink,
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ))
              .toList(),
        );
      },
    );
  }
}

class _AdminDetailData {
  final String label;
  final String value;
  final IconData icon;

  const _AdminDetailData(this.label, this.value, this.icon);
}

class _AdminConversationTimeline extends StatelessWidget {
  final List<_AdminTicketMessage> messages;

  const _AdminConversationTimeline({required this.messages});

  @override
  Widget build(BuildContext context) {
    if (messages.isEmpty) {
      return const _AdminTextPanel(text: 'No replies yet.');
    }
    return Column(
      children: messages
          .map((message) => Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: _AdminMessageBubble(message: message),
              ))
          .toList(),
    );
  }
}

class _AdminMessageBubble extends StatelessWidget {
  final _AdminTicketMessage message;

  const _AdminMessageBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    final isStudent = message.senderRole.toLowerCase() == 'student';
    final color = isStudent ? const Color(0xFFF8FAFC) : const Color(0xFFFFF7ED);
    final borderColor =
        isStudent ? DesignTokens.border : const Color(0xFFFED7AA);
    final accent = isStudent ? DesignTokens.muted : DesignTokens.maroon;
    return Align(
      alignment: isStudent ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 680),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: borderColor),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  isStudent
                      ? Icons.person_outline_rounded
                      : Icons.admin_panel_settings_rounded,
                  color: accent,
                  size: 18,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '${message.senderName} - ${_adminTitleCase(message.senderRole)}',
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: accent,
                      fontWeight: FontWeight.w900,
                      fontSize: 12,
                    ),
                  ),
                ),
                Text(
                  _adminFormatDate(message.createdAt),
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 9),
            Text(
              message.message,
              style: const TextStyle(color: DesignTokens.ink, height: 1.45),
            ),
          ],
        ),
      ),
    );
  }
}

class _AdminTextPanel extends StatelessWidget {
  final String text;

  const _AdminTextPanel({required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Text(
        text,
        style: const TextStyle(color: DesignTokens.ink, height: 1.45),
      ),
    );
  }
}

class _AdminSectionTitle extends StatelessWidget {
  final String label;

  const _AdminSectionTitle(this.label);

  @override
  Widget build(BuildContext context) {
    return Text(
      label,
      style: const TextStyle(
        fontWeight: FontWeight.w900,
        color: DesignTokens.ink,
        fontSize: 15,
      ),
    );
  }
}

class _AdminMetaItem extends StatelessWidget {
  final IconData icon;
  final String label;

  const _AdminMetaItem({required this.icon, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, color: DesignTokens.muted, size: 16),
        const SizedBox(width: 5),
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 260),
          child: Text(
            label,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ],
    );
  }
}

class _AdminStatusChip extends StatelessWidget {
  final String status;

  const _AdminStatusChip({required this.status});

  @override
  Widget build(BuildContext context) {
    final color = _adminStatusColor(status);
    return _AdminChip(label: status, icon: Icons.circle_rounded, color: color);
  }
}

class _AdminPriorityChip extends StatelessWidget {
  final String priority;

  const _AdminPriorityChip({required this.priority});

  @override
  Widget build(BuildContext context) {
    final color = _adminPriorityColor(priority);
    return _AdminChip(
      label: priority,
      icon: Icons.priority_high_rounded,
      color: color,
    );
  }
}

class _AdminChip extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color color;

  const _AdminChip({
    required this.label,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.28)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: color, size: 12),
          const SizedBox(width: 5),
          Text(
            label,
            style: TextStyle(
              color: color,
              fontSize: 11,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }
}

class _AdminPlaceholderPanel extends StatelessWidget {
  final IconData icon;
  final String title;
  final String description;

  const _AdminPlaceholderPanel({
    required this.icon,
    required this.title,
    required this.description,
  });

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StudentIconBox(icon: icon, color: DesignTokens.maroon, size: 48),
          const SizedBox(width: 14),
          Expanded(
            child: StudentSectionTitle(
              title: title,
              subtitle: description,
            ),
          ),
        ],
      ),
    );
  }
}

class _AdminNotice extends StatelessWidget {
  final IconData icon;
  final String message;

  const _AdminNotice({required this.icon, required this.message});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: StudentPanel(
        shadow: false,
        child: Row(
          children: [
            Icon(icon, color: DesignTokens.maroon),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                message,
                style: const TextStyle(
                  color: DesignTokens.muted,
                  height: 1.35,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AdminMetricData {
  final String label;
  final String value;
  final IconData icon;
  final String? statusFilter;

  const _AdminMetricData(this.label, this.value, this.icon,
      {this.statusFilter});
}

class _AdminTicketMessage {
  final String id;
  final String ticketId;
  final String senderId;
  final String senderRole;
  final String senderName;
  final String message;
  final DateTime createdAt;

  const _AdminTicketMessage({
    required this.id,
    required this.ticketId,
    required this.senderId,
    required this.senderRole,
    required this.senderName,
    required this.message,
    required this.createdAt,
  });

  factory _AdminTicketMessage.fromJson(Map<String, dynamic> json) {
    return _AdminTicketMessage(
      id: (json['id'] ?? '').toString(),
      ticketId: (json['ticket_id'] ?? '').toString(),
      senderId: (json['sender_id'] ?? '').toString(),
      senderRole: (json['sender_role'] ?? 'office').toString(),
      senderName: (json['sender_name'] ?? 'Office').toString(),
      message: (json['message'] ?? '').toString(),
      createdAt: _adminParseDate(json['created_at']),
    );
  }
}

class _AdminTicketEntry {
  final String id;
  final String userId;
  final String userName;
  final String? userEmail;
  final String subject;
  final String status;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DateTime? resolvedAt;
  final DateTime? closedAt;
  final String category;
  final String assignedOffice;
  final String priority;
  final String description;
  final double? confidenceScore;
  final bool sourceFromChatbot;
  final List<_AdminTicketMessage> messages;

  const _AdminTicketEntry({
    required this.id,
    required this.userId,
    required this.userName,
    required this.userEmail,
    required this.subject,
    required this.status,
    required this.createdAt,
    required this.updatedAt,
    required this.resolvedAt,
    required this.closedAt,
    required this.category,
    required this.assignedOffice,
    required this.priority,
    required this.description,
    required this.confidenceScore,
    required this.sourceFromChatbot,
    required this.messages,
  });

  factory _AdminTicketEntry.fromJson(Map<String, dynamic> json) {
    final rawMessages =
        json['messages'] is List ? json['messages'] as List : const <dynamic>[];
    return _AdminTicketEntry(
      id: (json['id'] ?? '').toString(),
      userId: (json['user_id'] ?? '').toString(),
      userName: (json['user_name'] ?? 'Student').toString(),
      userEmail: _nullableAdminString(json['user_email']),
      subject: (json['original_question'] ?? 'Untitled concern').toString(),
      status: _adminTitleStatus((json['status'] ?? 'Open').toString()),
      createdAt: _adminParseDate(json['created_at']),
      updatedAt: _adminParseDate(json['updated_at']),
      resolvedAt: _adminParseNullableDate(json['resolved_at']),
      closedAt: _adminParseNullableDate(json['closed_at']),
      category: (json['category'] ?? 'General').toString(),
      assignedOffice: (json['assigned_office'] ?? 'Support Office').toString(),
      priority: _adminTitlePriority((json['priority'] ?? 'Low').toString()),
      description: (json['description'] ?? '').toString(),
      confidenceScore: _parseDouble(json['confidence_score']),
      sourceFromChatbot: json['source_from_chatbot'] == true,
      messages: rawMessages
          .whereType<Map>()
          .map((item) =>
              _AdminTicketMessage.fromJson(Map<String, dynamic>.from(item)))
          .toList(),
    );
  }

  bool matches(
    String query,
    String statusFilter,
    String priorityFilter,
    String officeFilter,
  ) {
    final normalized = query.trim().toLowerCase();
    final email = userEmail ?? '';
    final matchesQuery = normalized.isEmpty ||
        id.toLowerCase().contains(normalized) ||
        subject.toLowerCase().contains(normalized) ||
        description.toLowerCase().contains(normalized) ||
        assignedOffice.toLowerCase().contains(normalized) ||
        category.toLowerCase().contains(normalized) ||
        userName.toLowerCase().contains(normalized) ||
        email.toLowerCase().contains(normalized);
    final matchesStatus = statusFilter == 'All' || status == statusFilter;
    final matchesPriority =
        priorityFilter == 'All' || priority == priorityFilter;
    final matchesOffice =
        officeFilter == 'All' || assignedOffice == officeFilter;
    return matchesQuery && matchesStatus && matchesPriority && matchesOffice;
  }
}

class _TicketStats {
  final int total;
  final int open;
  final int inProgress;
  final int closed;
  final Map<String, dynamic> byOffice;

  const _TicketStats({
    required this.total,
    required this.open,
    required this.inProgress,
    required this.closed,
    required this.byOffice,
  });

  String get totalText => total.toString();
  String get openText => open.toString();
  String get inProgressText => inProgress.toString();
  String get closedText => closed.toString();
  String get officeCountText => byOffice.length.toString();

  factory _TicketStats.fromJson(Map<String, dynamic> json) {
    return _TicketStats(
      total: _readInt(json['total']),
      open: _readInt(json['open']),
      inProgress: _readInt(json['in_progress']),
      closed: _readInt(json['closed']),
      byOffice: json['by_office'] is Map
          ? Map<String, dynamic>.from(json['by_office'] as Map)
          : const {},
    );
  }
}

Future<_TicketStats> _loadTicketStats(BuildContext context) async {
  final request = html.HttpRequest();
  request.open('GET', '${AppConfig.resolvedApiBase}/tickets/statistics');
  AuthScope.of(context).ticketHeaders().forEach(request.setRequestHeader);
  request.send();
  await request.onLoadEnd.first;
  final data = _decodeObject(request.responseText);
  final statusCode = request.status ?? 0;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not load ticket statistics.'));
  }
  return _TicketStats.fromJson(data);
}

Map<String, dynamic> _decodeObject(String? responseText) {
  final text = (responseText ?? '').trim();
  if (text.isEmpty) return <String, dynamic>{};
  try {
    final decoded = jsonDecode(text);
    return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
  } catch (_) {
    return <String, dynamic>{'detail': text};
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
  return message.isEmpty
      ? 'The backend did not return a usable response.'
      : message;
}

int _readInt(Object? value) {
  if (value is num) return value.toInt();
  return int.tryParse(value?.toString() ?? '') ?? 0;
}

InputDecoration _adminInputDecoration({
  required String hintText,
  required IconData icon,
}) {
  return InputDecoration(
    hintText: hintText,
    prefixIcon: Icon(icon, size: 20),
    filled: true,
    fillColor: Colors.white,
    contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: DesignTokens.border),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: DesignTokens.border),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: DesignTokens.maroon, width: 1.4),
    ),
  );
}

List<String> _mergeOption(List<String> values, String current) {
  final merged = <String>{...values.where((value) => value.trim().isNotEmpty)};
  if (current.trim().isNotEmpty) merged.add(current);
  return merged.toList()..sort();
}

String? _nullableAdminString(Object? value) {
  final text = value?.toString().trim();
  if (text == null || text.isEmpty) return null;
  return text;
}

double? _parseDouble(Object? value) {
  if (value is num) return value.toDouble();
  return double.tryParse(value?.toString() ?? '');
}

DateTime _adminParseDate(Object? value) {
  final text = value?.toString();
  if (text == null || text.isEmpty) return DateTime.now();
  return DateTime.tryParse(text)?.toLocal() ?? DateTime.now();
}

DateTime? _adminParseNullableDate(Object? value) {
  final text = value?.toString();
  if (text == null || text.isEmpty) return null;
  return DateTime.tryParse(text)?.toLocal();
}

String _adminTitleStatus(String value) {
  final normalized = value.trim().toLowerCase().replaceAll('_', ' ');
  if (normalized == 'in progress') return 'In Progress';
  if (normalized == 'resolved') return 'Resolved';
  if (normalized == 'closed') return 'Closed';
  return 'Open';
}

String _adminTitlePriority(String value) {
  final normalized = value.trim().toLowerCase();
  if (normalized == 'urgent') return 'Urgent';
  if (normalized == 'high') return 'High';
  if (normalized == 'medium') return 'Medium';
  return 'Low';
}

String _adminTitleCase(String value) {
  return value
      .split(RegExp(r'[\s_]+'))
      .where((part) => part.isNotEmpty)
      .map((part) => part[0].toUpperCase() + part.substring(1).toLowerCase())
      .join(' ');
}

Color _adminStatusColor(String status) {
  if (status == 'Open') return const Color(0xFF2563EB);
  if (status == 'In Progress') return const Color(0xFFF97316);
  if (status == 'Resolved') return const Color(0xFF16A34A);
  if (status == 'Closed') return const Color(0xFF475569);
  return DesignTokens.maroon;
}

Color _adminPriorityColor(String priority) {
  if (priority == 'Urgent') return const Color(0xFFB91C1C);
  if (priority == 'High') return const Color(0xFFDC2626);
  if (priority == 'Medium') return const Color(0xFFD97706);
  if (priority == 'Low') return const Color(0xFF16A34A);
  return DesignTokens.muted;
}

String _adminFormatDate(DateTime date) {
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  return '${months[date.month - 1]} ${date.day}';
}

String _adminFormatFullDate(DateTime date) {
  final hour = date.hour == 0
      ? 12
      : date.hour > 12
          ? date.hour - 12
          : date.hour;
  final minute = date.minute.toString().padLeft(2, '0');
  final meridiem = date.hour >= 12 ? 'PM' : 'AM';
  return '${_adminFormatDate(date)}, ${date.year} $hour:$minute $meridiem';
}
