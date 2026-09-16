import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import '../app_config.dart';
import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../services/api_client.dart';
import '../services/download_file.dart';
import '../services/file_pick.dart';
import '../services/kb_compose_helpers.dart';
import '../widgets/sidebar.dart';
import '../widgets/student_ui.dart';
import 'admin_generate_articles_page.dart';
import 'admin_scaffold.dart';
import 'login_page.dart';

part 'staff_ticket_console.dart';
part 'office_account_page.dart';
part 'admin_offices_page.dart';
part 'admin_all_tickets_page.dart';
part 'admin_users_roles_page.dart';

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
      _AdminMetricData(
          'High Priority', stats?.highPriorityText ?? '-', Icons.priority_high_rounded),
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
                'Use All Tickets, Knowledge Base, Generate Articles, Announcements, Users & Roles, Offices, and Reports from the sidebar.',
          ),
        ],
      ),
    );
  }
}

class OfficeDashboardPage extends StatefulWidget {
  /// Seeded tickets skip network load. Widget tests only.
  @visibleForTesting
  final List<Map<String, dynamic>>? debugTickets;

  /// Frozen clock for widget tests.
  @visibleForTesting
  final DateTime? debugNow;

  const OfficeDashboardPage({
    super.key,
    this.debugTickets,
    this.debugNow,
  });

  @override
  State<OfficeDashboardPage> createState() => _OfficeDashboardPageState();
}

class _OfficeDashboardPageState extends State<OfficeDashboardPage> {
  final List<_AdminTicketEntry> _tickets = [];
  bool _loading = false;
  String? _error;
  bool _requestedInitialLoad = false;

  @override
  void initState() {
    super.initState();
    final seeded = widget.debugTickets;
    if (seeded != null) {
      _requestedInitialLoad = true;
      _tickets.addAll(
        seeded.map(
          (item) => _AdminTicketEntry.fromJson(Map<String, dynamic>.from(item)),
        ),
      );
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    if (auth.role == 'office' && !_requestedInitialLoad) {
      _requestedInitialLoad = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _loadTickets();
      });
    }
  }

  Future<void> _loadTickets() async {
    final officeError = _officeAssignmentError(context);
    if (officeError != null) {
      setState(() => _error = officeError);
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final tickets = await _loadOfficeTickets(context);
      setState(() {
        _tickets
          ..clear()
          ..addAll(tickets);
      });
    } catch (error) {
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  int get _openCount =>
      _tickets.where((ticket) => ticket.status == 'Open').length;

  int get _inProgressCount =>
      _tickets.where((ticket) => ticket.status == 'In Progress').length;

  int get _closedCount => _tickets
      .where((ticket) =>
          ticket.status == 'Closed' || ticket.status == 'Resolved')
      .length;

  int get _highPriorityCount => _tickets
      .where((ticket) =>
          ticket.priority == 'High' || ticket.priority == 'Urgent')
      .length;

  List<_AdminTicketEntry> get _recentTickets {
    final items = [..._tickets]
      ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return items.take(8).toList();
  }

  void _openAssignedTickets({String? ticketId}) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => OfficeAssignedTicketsPage(
          initialSelectedTicketId: ticketId,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final officeName =
        AuthScope.of(context).currentUser?.officeName ?? 'Office';
    final now = widget.debugNow ?? DateTime.now();

    return OfficeScaffold(
      current: StudentNavItem.officeDashboard,
      title: 'Office Dashboard',
      description: 'Overview of workload for $officeName.',
      fillBody: true,
      showHeader: false,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_loading) const LinearProgressIndicator(minHeight: 3),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
              child: _AdminNotice(
                icon: Icons.info_outline_rounded,
                message: _error!,
              ),
            ),
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final wide = constraints.maxWidth >= 900;
                return SingleChildScrollView(
                  padding: EdgeInsets.fromLTRB(
                    wide ? 24 : 14,
                    wide ? 20 : 14,
                    wide ? 24 : 14,
                    24,
                  ),
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 1180),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _OfficeDashboardHeader(
                          officeName: officeName,
                          now: now,
                        ),
                        const SizedBox(height: 18),
                        _OfficeDashboardStatsRow(
                          assigned: _tickets.length,
                          open: _openCount,
                          inProgress: _inProgressCount,
                          closed: _closedCount,
                          highPriority: _highPriorityCount,
                        ),
                        const SizedBox(height: 18),
                        _OfficeRecentTicketsPanel(
                          tickets: _recentTickets,
                          onViewAll: () => _openAssignedTickets(),
                          onOpenTicket: (ticket) =>
                              _openAssignedTickets(ticketId: ticket.id),
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class OfficeAssignedTicketsPage extends StatefulWidget {
  final String initialStatusFilter;
  final String initialSearch;
  final String? initialSelectedTicketId;
  /// Seeded tickets skip network load. Widget tests only.
  @visibleForTesting
  final List<Map<String, dynamic>>? debugTickets;

  const OfficeAssignedTicketsPage({
    super.key,
    this.initialStatusFilter = 'All',
    this.initialSearch = '',
    this.initialSelectedTicketId,
    this.debugTickets,
  });

  @override
  State<OfficeAssignedTicketsPage> createState() =>
      _OfficeAssignedTicketsPageState();
}

class _OfficeAssignedTicketsPageState extends State<OfficeAssignedTicketsPage> {
  final List<_AdminTicketEntry> _tickets = [];
  final TextEditingController _searchCtrl = TextEditingController();
  bool _loading = false;
  String? _error;
  late String _statusFilter;
  String _priorityFilter = 'All';
  bool _requestedInitialLoad = false;

  @override
  void initState() {
    super.initState();
    _statusFilter = widget.initialStatusFilter;
    _searchCtrl.text = widget.initialSearch;
    _searchCtrl.addListener(() => setState(() {}));
    final seeded = widget.debugTickets;
    if (seeded != null) {
      _requestedInitialLoad = true;
      _tickets.addAll(
        seeded.map(
          (item) => _AdminTicketEntry.fromJson(Map<String, dynamic>.from(item)),
        ),
      );
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    if (auth.role == 'office' && !_requestedInitialLoad) {
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
    final officeError = _officeAssignmentError(context);
    if (officeError != null) {
      setState(() => _error = officeError);
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final tickets = await _loadOfficeTickets(context);
      setState(() {
        _tickets
          ..clear()
          ..addAll(tickets);
      });
    } catch (error) {
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
    String message, {
    bool isInternal = false,
  }) async {
    final result = await ApiClient.send(
      method: 'POST',
      url: '${AppConfig.resolvedApiBase}/tickets/${ticket.id}/replies',
      headers: {...AuthScope.of(context).ticketHeaders()},
      jsonBody: {'message': message, 'is_internal': isInternal},
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
    });
  }

  @override
  Widget build(BuildContext context) {
    final officeName =
        AuthScope.of(context).currentUser?.officeName ?? 'Office';
    final filteredTickets = _tickets
        .where((ticket) => ticket.matches(
              _searchCtrl.text,
              _statusFilter,
              _priorityFilter,
              'All',
            ))
        .toList();

    return OfficeScaffold(
      current: StudentNavItem.officeAssignedTickets,
      title: 'Assigned Tickets',
      description: 'Manage tickets routed to $officeName.',
      fillBody: true,
      child: _StaffTicketConsole(
        tickets: _tickets,
        filteredTickets: filteredTickets,
        searchCtrl: _searchCtrl,
        statusFilter: _statusFilter,
        onStatusChanged: (value) => setState(() => _statusFilter = value),
        priorityFilter: _priorityFilter,
        onPriorityChanged: (value) => setState(() => _priorityFilter = value),
        loading: _loading,
        error: _error,
        onRefresh: widget.debugTickets == null ? _loadTickets : () async {},
        officeOptions: const [],
        allowReassignment: false,
        listTitle: 'Assigned Tickets',
        replyHint: 'Write a reply…',
        onUpdate: _patchTicket,
        onReply: _replyToTicket,
        onTicketChanged: _replaceTicket,
        initialSelectedId: widget.initialSelectedTicketId,
      ),
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
  bool _requestedInitialLoad = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    if (auth.role == 'admin' && !_requestedInitialLoad) {
      _requestedInitialLoad = true;
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

  Future<void> _exportSummary() async {
    final stats = _stats;
    if (stats == null) return;
    final text = stats.toReportText();
    await Clipboard.setData(ClipboardData(text: text));
    await downloadTextFile(
      filename:
          'aska_ticket_report_${DateTime.now().toIso8601String().split('T').first}.txt',
      text: text,
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Report copied and downloaded.')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final stats = _stats;
    return AdminScaffold(
      current: StudentNavItem.adminReports,
      title: 'Reports / Statistics',
      description:
          'Track ticket volume, priority mix, and office workload for administrative review.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_loading) const LinearProgressIndicator(minHeight: 3),
          if (_error != null)
            _AdminNotice(icon: Icons.info_outline_rounded, message: _error!),
          Row(
            children: [
              OutlinedButton.icon(
                onPressed: _loading ? null : _loadStats,
                icon: const Icon(Icons.refresh_rounded, size: 18),
                label: const Text('Refresh'),
              ),
              const SizedBox(width: 8),
              ElevatedButton.icon(
                onPressed: stats == null || _loading ? null : _exportSummary,
                icon: const Icon(Icons.download_rounded, size: 18),
                label: const Text('Export summary'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: DesignTokens.maroon,
                  foregroundColor: Colors.white,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          if (stats == null && !_loading)
            const _AdminPlaceholderPanel(
              icon: Icons.query_stats_rounded,
              title: 'No report data yet',
              description:
                  'Ticket statistics will appear here after tickets are created.',
            )
          else if (stats != null) ...[
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
                  children: [
                    _AdminMetricCard(
                      data: _AdminMetricData(
                          'Total', stats.totalText, Icons.confirmation_number_rounded),
                    ),
                    _AdminMetricCard(
                      data: _AdminMetricData(
                          'Open', stats.openText, Icons.mark_email_unread_rounded),
                    ),
                    _AdminMetricCard(
                      data: _AdminMetricData(
                          'In Progress', stats.inProgressText, Icons.timelapse_rounded),
                    ),
                    _AdminMetricCard(
                      data: _AdminMetricData(
                          'Resolved', stats.resolvedText, Icons.task_alt_rounded),
                    ),
                    _AdminMetricCard(
                      data: _AdminMetricData(
                          'Closed', stats.closedText, Icons.check_circle_rounded),
                    ),
                    _AdminMetricCard(
                      data: _AdminMetricData('High / Urgent open',
                          stats.highPriorityText, Icons.priority_high_rounded),
                    ),
                  ],
                );
              },
            ),
            const SizedBox(height: 16),
            StudentPanel(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const StudentSectionTitle(
                    title: 'Status mix',
                    subtitle: 'Share of tickets by workflow status.',
                  ),
                  const SizedBox(height: 12),
                  ..._statusBars(stats),
                ],
              ),
            ),
            const SizedBox(height: 16),
            LayoutBuilder(
              builder: (context, constraints) {
                final wide = constraints.maxWidth >= 900;
                final officePanel = StudentPanel(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const StudentSectionTitle(
                        title: 'By office',
                        subtitle: 'Assigned ticket volume per campus office.',
                      ),
                      const SizedBox(height: 12),
                      if (stats.byOffice.isEmpty)
                        const Text('No office assignments yet.',
                            style: TextStyle(color: DesignTokens.muted))
                      else
                        ...stats.sortedOfficeEntries.map(
                          (entry) => _ReportCountRow(
                            label: entry.key,
                            count: entry.value,
                            total: stats.total,
                          ),
                        ),
                    ],
                  ),
                );
                final priorityPanel = StudentPanel(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const StudentSectionTitle(
                        title: 'By priority',
                        subtitle: 'Urgent and High need faster office response.',
                      ),
                      const SizedBox(height: 12),
                      if (stats.byPriority.isEmpty)
                        const Text('No priority data yet.',
                            style: TextStyle(color: DesignTokens.muted))
                      else
                        ...stats.sortedPriorityEntries.map(
                          (entry) => _ReportCountRow(
                            label: entry.key,
                            count: entry.value,
                            total: stats.total,
                          ),
                        ),
                      const SizedBox(height: 18),
                      const StudentSectionTitle(
                        title: 'Top categories',
                        subtitle: 'Most common ticket categories.',
                      ),
                      const SizedBox(height: 12),
                      if (stats.byCategory.isEmpty)
                        const Text('No category data yet.',
                            style: TextStyle(color: DesignTokens.muted))
                      else
                        ...stats.sortedCategoryEntries.take(8).map(
                              (entry) => _ReportCountRow(
                                label: entry.key,
                                count: entry.value,
                                total: stats.total,
                              ),
                            ),
                    ],
                  ),
                );
                if (!wide) {
                  return Column(
                    children: [
                      officePanel,
                      const SizedBox(height: 16),
                      priorityPanel,
                    ],
                  );
                }
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: officePanel),
                    const SizedBox(width: 16),
                    Expanded(child: priorityPanel),
                  ],
                );
              },
            ),
          ],
        ],
      ),
    );
  }

  List<Widget> _statusBars(_TicketStats stats) {
    final rows = <Map<String, Object>>[
      {
        'label': 'Open',
        'count': stats.open,
        'color': const Color(0xFFB45309),
      },
      {
        'label': 'In Progress',
        'count': stats.inProgress,
        'color': DesignTokens.maroon,
      },
      {
        'label': 'Resolved',
        'count': stats.resolved,
        'color': const Color(0xFF047857),
      },
      {
        'label': 'Closed',
        'count': stats.closed,
        'color': const Color(0xFF475569),
      },
    ];
    return rows
        .map(
          (row) => _ReportCountRow(
            label: row['label'] as String,
            count: row['count'] as int,
            total: stats.total,
            color: row['color'] as Color,
          ),
        )
        .toList();
  }
}

class _ReportCountRow extends StatelessWidget {
  final String label;
  final int count;
  final int total;
  final Color color;

  const _ReportCountRow({
    required this.label,
    required this.count,
    required this.total,
    this.color = DesignTokens.maroon,
  });

  @override
  Widget build(BuildContext context) {
    final ratio = total <= 0 ? 0.0 : (count / total).clamp(0.0, 1.0);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    color: DesignTokens.ink,
                  ),
                ),
              ),
              Text(
                '$count',
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  color: color,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: ratio,
              minHeight: 8,
              backgroundColor: const Color(0xFFE2E8F0),
              color: color,
            ),
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

class _CreateOfficeAccountDialog extends StatefulWidget {
  final List<_AdminOfficeEntry> offices;
  final String? initialOfficeId;
  final Future<_AdminUserEntry> Function({
    required String fullName,
    required String email,
    required String password,
    required String officeId,
  })? onCreate;

  const _CreateOfficeAccountDialog({
    required this.offices,
    this.initialOfficeId,
    this.onCreate,
  });

  @override
  State<_CreateOfficeAccountDialog> createState() =>
      _CreateOfficeAccountDialogState();
}

class _CreateOfficeAccountDialogState extends State<_CreateOfficeAccountDialog> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  late String? _officeId;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _officeId = widget.initialOfficeId ??
        (widget.offices.isNotEmpty ? widget.offices.first.id : null);
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (_officeId == null || _officeId!.isEmpty) {
      setState(() => _error = 'Select an office.');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final user = widget.onCreate != null
          ? await widget.onCreate!(
              fullName: _nameCtrl.text.trim(),
              email: _emailCtrl.text.trim(),
              password: _passwordCtrl.text,
              officeId: _officeId!,
            )
          : await _createOfficeAccountRequest(
              context,
              fullName: _nameCtrl.text.trim(),
              email: _emailCtrl.text.trim(),
              password: _passwordCtrl.text,
              officeId: _officeId!,
            );
      if (!mounted) return;
      Navigator.of(context).pop(user);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Create office account'),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                key: const Key('admin-offices-staff-name'),
                controller: _nameCtrl,
                decoration: const InputDecoration(labelText: 'Full name'),
                validator: (value) =>
                    (value == null || value.trim().isEmpty)
                        ? 'Enter a name.'
                        : null,
              ),
              const SizedBox(height: 10),
              TextFormField(
                key: const Key('admin-offices-staff-email'),
                controller: _emailCtrl,
                decoration: const InputDecoration(labelText: 'Email'),
                validator: (value) {
                  final text = value?.trim() ?? '';
                  if (text.isEmpty) return 'Enter an email.';
                  if (!text.contains('@')) return 'Enter a valid email.';
                  return null;
                },
              ),
              const SizedBox(height: 10),
              TextFormField(
                key: const Key('admin-offices-staff-password'),
                controller: _passwordCtrl,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'Password'),
                validator: (value) {
                  final text = value ?? '';
                  if (text.length < 8) return 'Use at least 8 characters.';
                  return null;
                },
              ),
              const SizedBox(height: 10),
              DropdownButtonFormField<String>(
                value: _officeId,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Office'),
                items: widget.offices
                    .map(
                      (office) => DropdownMenuItem(
                        value: office.id,
                        child: Text(
                          office.name,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    )
                    .toList(),
                onChanged: (value) => setState(() => _officeId = value),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: const TextStyle(color: Color(0xFFB91C1C))),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _loading ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          key: const Key('admin-offices-staff-submit'),
          onPressed: _loading ? null : _submit,
          style: ElevatedButton.styleFrom(
            backgroundColor: DesignTokens.maroon,
            foregroundColor: Colors.white,
          ),
          child: _loading
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                )
              : const Text('Create'),
        ),
      ],
    );
  }
}

class _CreateFacultyAccountDialog extends StatefulWidget {
  const _CreateFacultyAccountDialog();

  @override
  State<_CreateFacultyAccountDialog> createState() =>
      _CreateFacultyAccountDialogState();
}

class _CreateFacultyAccountDialogState
    extends State<_CreateFacultyAccountDialog> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _nameCtrl.dispose();
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final user = await _createFacultyAccountRequest(
        context,
        fullName: _nameCtrl.text.trim(),
        email: _emailCtrl.text.trim(),
        password: _passwordCtrl.text,
      );
      if (!mounted) return;
      Navigator.of(context).pop(user);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Create faculty account'),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _nameCtrl,
                decoration: const InputDecoration(labelText: 'Full name'),
                validator: (value) => (value == null || value.trim().isEmpty)
                    ? 'Enter a name.'
                    : null,
              ),
              const SizedBox(height: 10),
              TextFormField(
                controller: _emailCtrl,
                decoration: const InputDecoration(labelText: 'Email'),
                validator: (value) {
                  final text = value?.trim() ?? '';
                  if (text.isEmpty) return 'Enter an email.';
                  if (!text.contains('@')) return 'Enter a valid email.';
                  return null;
                },
              ),
              const SizedBox(height: 10),
              TextFormField(
                controller: _passwordCtrl,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'Temporary password',
                  helperText: 'At least 10 characters with a letter and number.',
                ),
                validator: (value) {
                  final text = value ?? '';
                  if (text.length < 10) return 'Use at least 10 characters.';
                  if (!RegExp(r'[A-Za-z]').hasMatch(text) ||
                      !RegExp(r'\d').hasMatch(text)) {
                    return 'Include a letter and a number.';
                  }
                  return null;
                },
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: const TextStyle(color: Color(0xFFB91C1C))),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _loading ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: _loading ? null : _submit,
          style: ElevatedButton.styleFrom(
            backgroundColor: DesignTokens.maroon,
            foregroundColor: Colors.white,
          ),
          child: _loading
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                )
              : const Text('Create'),
        ),
      ],
    );
  }
}

class _CreateOfficeDialog extends StatefulWidget {
  final Future<_AdminOfficeEntry> Function({
    required String name,
    required String serviceCategory,
    required String description,
  })? onCreate;

  const _CreateOfficeDialog({this.onCreate});

  @override
  State<_CreateOfficeDialog> createState() => _CreateOfficeDialogState();
}

class _CreateOfficeDialogState extends State<_CreateOfficeDialog> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _categoryCtrl = TextEditingController();
  final _descriptionCtrl = TextEditingController();
  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _nameCtrl.dispose();
    _categoryCtrl.dispose();
    _descriptionCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final office = widget.onCreate != null
          ? await widget.onCreate!(
              name: _nameCtrl.text.trim(),
              serviceCategory: _categoryCtrl.text.trim(),
              description: _descriptionCtrl.text.trim(),
            )
          : await _createOfficeRequest(
              context,
              name: _nameCtrl.text.trim(),
              serviceCategory: _categoryCtrl.text.trim(),
              description: _descriptionCtrl.text.trim(),
            );
      if (!mounted) return;
      Navigator.of(context).pop(office);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Add campus office'),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                key: const Key('admin-offices-create-name'),
                controller: _nameCtrl,
                decoration: const InputDecoration(labelText: 'Office name'),
                validator: (value) => (value == null || value.trim().length < 2)
                    ? 'Enter an office name.'
                    : null,
              ),
              const SizedBox(height: 10),
              TextFormField(
                key: const Key('admin-offices-create-category'),
                controller: _categoryCtrl,
                decoration: const InputDecoration(
                  labelText: 'Service category (optional)',
                ),
              ),
              const SizedBox(height: 10),
              TextFormField(
                key: const Key('admin-offices-create-description'),
                controller: _descriptionCtrl,
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: 'Description (optional)',
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: const TextStyle(color: Color(0xFFB91C1C))),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _loading ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          key: const Key('admin-offices-create-submit'),
          onPressed: _loading ? null : _submit,
          style: ElevatedButton.styleFrom(
            backgroundColor: DesignTokens.maroon,
            foregroundColor: Colors.white,
          ),
          child: _loading
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                )
              : const Text('Create'),
        ),
      ],
    );
  }
}

class OfficeScaffold extends StatelessWidget {
  final StudentNavItem current;
  final String title;
  final String description;
  final Widget child;
  final bool fillBody;
  final bool showHeader;

  const OfficeScaffold({
    super.key,
    required this.current,
    required this.title,
    required this.description,
    required this.child,
    this.fillBody = false,
    this.showHeader = true,
  });

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    if (auth.role != 'office') {
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
                    icon: Icons.business_center_rounded,
                    color: DesignTokens.maroon,
                    size: 52,
                  ),
                  const SizedBox(height: 14),
                  const StudentSectionTitle(
                    title: 'Office access required',
                    subtitle:
                        'Please log in with an office account to open this page.',
                  ),
                  const SizedBox(height: 16),
                  ElevatedButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => LoginPage(
                          returnTo: (_) => this,
                          message:
                              'Please log in with an office account to open office tools.',
                        ),
                      ),
                    ),
                    child: const Text('Login'),
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
        final Widget content;
        if (fillBody) {
          content = ColoredBox(
            color: DesignTokens.adminSurface,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (showHeader)
                  Padding(
                    padding: EdgeInsets.fromLTRB(
                      isWide ? 20 : 14,
                      isWide ? 16 : 12,
                      isWide ? 20 : 14,
                      8,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          title,
                          style: const TextStyle(
                            color: DesignTokens.ink,
                            fontSize: 22,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          description,
                          style: const TextStyle(
                            color: DesignTokens.muted,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
                Expanded(child: child),
              ],
            ),
          );
        } else {
          content = StudentPage(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                StudentPanel(
                  child: Row(
                    children: [
                      const StudentIconBox(
                        icon: Icons.business_center_rounded,
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
        }

        if (isWide) {
          return Scaffold(
            backgroundColor: DesignTokens.adminSurface,
            body: Row(
              children: [
                SizedBox(
                  width: DesignTokens.adminSidebarWidth,
                  child: AppSidebar(current: current),
                ),
                Expanded(child: content),
              ],
            ),
          );
        }

        return Scaffold(
          backgroundColor: DesignTokens.adminSurface,
          drawer: Drawer(
            backgroundColor: DesignTokens.adminSidebarBg,
            child: AppSidebar(current: current),
          ),
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

class _OfficeDashboardHeader extends StatelessWidget {
  final String officeName;
  final DateTime now;

  const _OfficeDashboardHeader({
    required this.officeName,
    required this.now,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'WELCOME BACK',
                style: TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1.1,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                'Office Dashboard',
                style: TextStyle(
                  color: DesignTokens.ink,
                  fontSize: 28,
                  fontWeight: FontWeight.w900,
                  height: 1.1,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'Overview of workload for $officeName.',
                style: const TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: 12),
        _OfficeDashboardClock(now: now),
      ],
    );
  }
}

class _OfficeDashboardClock extends StatelessWidget {
  final DateTime now;

  const _OfficeDashboardClock({required this.now});

  @override
  Widget build(BuildContext context) {
    final local = now.toLocal();
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.04),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(
            _officeDashboardDateLine(local),
            style: const TextStyle(
              color: DesignTokens.ink,
              fontSize: 12,
              fontWeight: FontWeight.w800,
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
      ),
    );
  }
}

class _OfficeDashboardStatsRow extends StatelessWidget {
  final int assigned;
  final int open;
  final int inProgress;
  final int closed;
  final int highPriority;

  const _OfficeDashboardStatsRow({
    required this.assigned,
    required this.open,
    required this.inProgress,
    required this.closed,
    required this.highPriority,
  });

  @override
  Widget build(BuildContext context) {
    final stats = [
      _OfficeDashboardStatData(
        label: 'Assigned Tickets',
        value: '$assigned',
        subtitle: 'Tickets assigned to your office',
        accent: const Color(0xFF7A1218),
      ),
      _OfficeDashboardStatData(
        label: 'Open Tickets',
        value: '$open',
        subtitle: 'Awaiting action',
        accent: const Color(0xFF3B82F6),
      ),
      _OfficeDashboardStatData(
        label: 'In Progress',
        value: '$inProgress',
        subtitle: 'Currently being handled',
        accent: const Color(0xFFF59E0B),
      ),
      _OfficeDashboardStatData(
        label: 'Closed Tickets',
        value: '$closed',
        subtitle: 'Resolved tickets',
        accent: const Color(0xFF22C55E),
      ),
      _OfficeDashboardStatData(
        label: 'High Priority',
        value: '$highPriority',
        subtitle: 'Requires immediate attention',
        accent: const Color(0xFFEF4444),
      ),
    ];

    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final columns = width >= 1080
            ? 5
            : width >= 820
                ? 3
                : width >= 520
                    ? 2
                    : 1;
        const gap = 12.0;
        final cardWidth = columns == 1
            ? width
            : (width - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: stats
              .map(
                (stat) => SizedBox(
                  width: cardWidth,
                  child: _OfficeDashboardStatCard(data: stat),
                ),
              )
              .toList(),
        );
      },
    );
  }
}

class _OfficeDashboardStatData {
  final String label;
  final String value;
  final String subtitle;
  final Color accent;

  const _OfficeDashboardStatData({
    required this.label,
    required this.value,
    required this.subtitle,
    required this.accent,
  });
}

class _OfficeDashboardStatCard extends StatelessWidget {
  final _OfficeDashboardStatData data;

  const _OfficeDashboardStatCard({required this.data});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.035),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(height: 3, color: data.accent),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  data.label,
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  data.value,
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontSize: 28,
                    fontWeight: FontWeight.w800,
                    height: 1,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  data.subtitle,
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    height: 1.3,
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

class _OfficeRecentTicketsPanel extends StatelessWidget {
  final List<_AdminTicketEntry> tickets;
  final VoidCallback onViewAll;
  final ValueChanged<_AdminTicketEntry> onOpenTicket;

  const _OfficeRecentTicketsPanel({
    required this.tickets,
    required this.onViewAll,
    required this.onOpenTicket,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.03),
      ),
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Recent Tickets',
                      style: TextStyle(
                        color: DesignTokens.ink,
                        fontSize: 18,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    SizedBox(height: 4),
                    Text(
                      'Latest tickets assigned to your office.',
                      style: TextStyle(
                        color: DesignTokens.muted,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
              TextButton(
                onPressed: onViewAll,
                style: TextButton.styleFrom(
                  foregroundColor: DesignTokens.maroon,
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                ),
                child: const Text(
                  'View all tickets →',
                  style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          if (tickets.isEmpty)
            const _OfficeRecentTicketsEmpty()
          else
            LayoutBuilder(
              builder: (context, constraints) {
                if (constraints.maxWidth < 760) {
                  return Column(
                    children: [
                      for (var i = 0; i < tickets.length; i++)
                        _OfficeRecentTicketCard(
                          index: i + 1,
                          ticket: tickets[i],
                          onTap: () => onOpenTicket(tickets[i]),
                        ),
                    ],
                  );
                }
                return _OfficeRecentTicketsTable(
                  tickets: tickets,
                  onOpenTicket: onOpenTicket,
                );
              },
            ),
        ],
      ),
    );
  }
}

class _OfficeRecentTicketsEmpty extends StatelessWidget {
  const _OfficeRecentTicketsEmpty();

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.symmetric(vertical: 48),
      child: Column(
        children: [
          Icon(
            Icons.description_outlined,
            size: 34,
            color: Color(0xFFCBD5E1),
          ),
          SizedBox(height: 12),
          Text(
            'No recent tickets',
            style: TextStyle(
              color: DesignTokens.ink,
              fontSize: 16,
              fontWeight: FontWeight.w800,
            ),
          ),
          SizedBox(height: 6),
          Text(
            'Tickets assigned to your office will appear here.',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: DesignTokens.muted,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _OfficeRecentTicketsTable extends StatelessWidget {
  final List<_AdminTicketEntry> tickets;
  final ValueChanged<_AdminTicketEntry> onOpenTicket;

  const _OfficeRecentTicketsTable({
    required this.tickets,
    required this.onOpenTicket,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(8, 0, 8, 8),
          child: Row(
            children: [
              SizedBox(
                width: 36,
                child: Text('#', style: _kTableHeader),
              ),
              Expanded(
                flex: 4,
                child: Text('TITLE', style: _kTableHeader),
              ),
              Expanded(
                flex: 2,
                child: Text('STATUS', style: _kTableHeader),
              ),
              Expanded(
                flex: 2,
                child: Text('PRIORITY', style: _kTableHeader),
              ),
              Expanded(
                flex: 2,
                child: Text('REQUESTER', style: _kTableHeader),
              ),
              Expanded(
                flex: 2,
                child: Text('DATE ASSIGNED', style: _kTableHeader),
              ),
            ],
          ),
        ),
        const Divider(height: 1, color: DesignTokens.border),
        for (var i = 0; i < tickets.length; i++) ...[
          _OfficeRecentTicketRow(
            index: i + 1,
            ticket: tickets[i],
            onTap: () => onOpenTicket(tickets[i]),
          ),
          if (i != tickets.length - 1)
            const Divider(height: 1, color: DesignTokens.border),
        ],
      ],
    );
  }
}

const TextStyle _kTableHeader = TextStyle(
  color: DesignTokens.muted,
  fontSize: 11,
  fontWeight: FontWeight.w800,
  letterSpacing: 0.4,
);

class _OfficeRecentTicketRow extends StatelessWidget {
  final int index;
  final _AdminTicketEntry ticket;
  final VoidCallback onTap;

  const _OfficeRecentTicketRow({
    required this.index,
    required this.ticket,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
          child: Row(
            children: [
              SizedBox(
                width: 36,
                child: Text(
                  '$index',
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
              ),
              Expanded(
                flex: 4,
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
              Expanded(
                flex: 2,
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: _AdminStatusChip(status: ticket.status),
                ),
              ),
              Expanded(
                flex: 2,
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: _AdminPriorityChip(priority: ticket.priority),
                ),
              ),
              Expanded(
                flex: 2,
                child: Text(
                  ticket.userName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              Expanded(
                flex: 2,
                child: Text(
                  _adminFormatAssignedDate(ticket.createdAt),
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
        ),
      ),
    );
  }
}

class _OfficeRecentTicketCard extends StatelessWidget {
  final int index;
  final _AdminTicketEntry ticket;
  final VoidCallback onTap;

  const _OfficeRecentTicketCard({
    required this.index,
    required this.ticket,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Material(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '#$index  ${ticket.subject}',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontWeight: FontWeight.w800,
                    fontSize: 13,
                  ),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: [
                    _AdminStatusChip(status: ticket.status),
                    _AdminPriorityChip(priority: ticket.priority),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  ticket.userName,
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  _adminFormatAssignedDate(ticket.createdAt),
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
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

class _AdminFilterDropdown extends StatelessWidget {
  final String label;
  final String value;
  final List<String> values;
  final IconData? icon;
  final ValueChanged<String> onChanged;

  const _AdminFilterDropdown({
    required this.label,
    required this.value,
    required this.values,
    this.icon,
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

class _AdminTicketDetailsDialog extends StatefulWidget {
  final _AdminTicketEntry ticket;
  final List<String> offices;
  final String controlsTitle;
  final String replyHint;
  final bool allowReassignment;
  final Future<_AdminTicketEntry> Function(Map<String, dynamic> payload)
      onUpdate;
  final Future<_AdminTicketEntry> Function(String message) onReply;

  const _AdminTicketDetailsDialog({
    required this.ticket,
    required this.offices,
    this.controlsTitle = 'Admin controls',
    this.replyHint = 'Write an admin reply',
    this.allowReassignment = true,
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
    final priorities = _mergeOption(const ['Low', 'Medium', 'High', 'Urgent'], _priority);
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
                        if (_ticket.kbConversionStatus == 'draft')
                          const _AdminKbBadge(
                            label: 'KB Draft',
                            color: Color(0xFFCA8A04),
                          ),
                        if (_ticket.kbConversionStatus == 'published')
                          const _AdminKbBadge(
                            label: 'KB Published',
                            color: Color(0xFF16A34A),
                          ),
                      ],
                    ),
                    const SizedBox(height: 18),
                    _AdminDetailGrid(ticket: _ticket),
                    if (_ticket.status == 'Resolved' ||
                        _ticket.status == 'Closed') ...[
                      const SizedBox(height: 20),
                      _AdminSectionTitle('Knowledge Base'),
                      const SizedBox(height: 10),
                      StudentPanel(
                        shadow: false,
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              _ticket.kbConversionStatus == 'published'
                                  ? 'This ticket already has a published knowledge article. Admins can unpublish it from the Article Library if it needs revision.'
                                  : _ticket.kbConversionStatus == 'draft'
                                      ? 'A draft FAQ already exists for this ticket. You can update it from the approved resolution.'
                                      : 'Convert the approved office answer into a draft FAQ so future users can get this answer from ASKa-Piyu.',
                              style: const TextStyle(
                                color: DesignTokens.muted,
                                height: 1.4,
                              ),
                            ),
                            const SizedBox(height: 12),
                            Align(
                              alignment: Alignment.centerRight,
                              child: Wrap(
                                spacing: 10,
                                runSpacing: 10,
                                alignment: WrapAlignment.end,
                                children: [
                                  if (AuthScope.of(context).role == 'admin' &&
                                      (_ticket.kbArticleId ?? '').isNotEmpty)
                                    OutlinedButton.icon(
                                      onPressed: () {
                                        openAdminPage(
                                          context,
                                          builder: (_) =>
                                              AdminGenerateArticlesPage(
                                            focusArticleId: _ticket.kbArticleId,
                                          ),
                                        );
                                      },
                                      icon: const Icon(
                                        Icons.open_in_new_rounded,
                                        size: 18,
                                      ),
                                      label: const Text('Open in Article Library'),
                                    ),
                                  if (_ticket.kbConversionStatus != 'published')
                                    ElevatedButton.icon(
                                      onPressed:
                                          _saving ? null : _convertToKnowledge,
                                      icon: const Icon(Icons.menu_book_outlined,
                                          size: 18),
                                      label: Text(
                                        _ticket.kbConversionStatus == 'none'
                                            ? 'Convert to Knowledge Base'
                                            : 'Update KB Draft',
                                      ),
                                      style: ElevatedButton.styleFrom(
                                        backgroundColor: DesignTokens.maroon,
                                        foregroundColor: Colors.white,
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                    const SizedBox(height: 20),
                    _AdminSectionTitle(widget.controlsTitle),
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
                                if (widget.allowReassignment) ...[
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
                                ],
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
                        hintText: widget.replyHint,
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
        if (widget.allowReassignment) 'assigned_office': _office,
        if (widget.allowReassignment) 'category': _categoryCtrl.text.trim(),
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

  Future<void> _convertToKnowledge() async {
    final latestStaff = _ticket.messages.reversed
        .where((m) =>
            m.senderRole == 'office' || m.senderRole == 'admin')
        .map((m) => m.message.trim())
        .firstWhere((m) => m.isNotEmpty, orElse: () => '');
    final titleCtrl = TextEditingController(text: _ticket.subject);
    final contentCtrl = TextEditingController(
      text: latestStaff.isEmpty
          ? '## Question\n\n${_ticket.subject}\n\n## Answer\n\n'
          : '## Question\n\n${_ticket.subject}\n\n## Answer\n\n$latestStaff',
    );
    var audience = 'auto';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              title: const Text('Convert to Knowledge Base'),
              content: SizedBox(
                width: 520,
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      TextField(
                        controller: titleCtrl,
                        decoration: const InputDecoration(
                          labelText: 'FAQ title',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        value: audience,
                        decoration: const InputDecoration(
                          labelText: 'Audience',
                          helperText:
                              'Auto infers student/faculty from the question and answer.',
                          border: OutlineInputBorder(),
                        ),
                        items: const [
                          DropdownMenuItem(
                              value: 'auto',
                              child: Text('Auto (infer from content)')),
                          DropdownMenuItem(
                              value: 'student', child: Text('Student')),
                          DropdownMenuItem(
                              value: 'faculty', child: Text('Faculty')),
                          DropdownMenuItem(
                              value: 'both', child: Text('Both')),
                        ],
                        onChanged: (value) {
                          if (value == null) return;
                          setDialogState(() => audience = value);
                        },
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: contentCtrl,
                        minLines: 8,
                        maxLines: 14,
                        decoration: const InputDecoration(
                          labelText: 'Approved answer / FAQ body',
                          border: OutlineInputBorder(),
                          alignLabelWithHint: true,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(false),
                  child: const Text('Cancel'),
                ),
                ElevatedButton(
                  onPressed: () => Navigator.of(dialogContext).pop(true),
                  child: const Text('Save draft'),
                ),
              ],
            );
          },
        );
      },
    );
    if (confirmed != true) {
      titleCtrl.dispose();
      contentCtrl.dispose();
      return;
    }

    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final body = <String, dynamic>{
        'title': titleCtrl.text.trim(),
        'content': contentCtrl.text.trim(),
      };
      if (audience != 'auto') {
        body['audience'] = audience;
      }
      final result = await ApiClient.send(
        method: 'POST',
        url:
            '${AppConfig.resolvedApiBase}/tickets/${_ticket.id}/convert-to-article',
        headers: {...AuthScope.of(context).ticketHeaders()},
        jsonBody: body,
      );
      final data = _decodeObject(result.body);
      final statusCode = result.statusCode;
      if (statusCode < 200 || statusCode >= 300) {
        throw StateError(_extractError(data, 'Could not convert ticket.'));
      }
      final articleId = (data['article_id'] ?? '').toString();
      final status =
          (data['kb_conversion_status'] ?? 'draft').toString().toLowerCase();
      setState(() {
        _ticket = _AdminTicketEntry(
          id: _ticket.id,
          userId: _ticket.userId,
          userName: _ticket.userName,
          userEmail: _ticket.userEmail,
          subject: _ticket.subject,
          status: _ticket.status,
          createdAt: _ticket.createdAt,
          updatedAt: _ticket.updatedAt,
          resolvedAt: _ticket.resolvedAt,
          closedAt: _ticket.closedAt,
          category: _ticket.category,
          assignedOffice: _ticket.assignedOffice,
          priority: _ticket.priority,
          description: _ticket.description,
          confidenceScore: _ticket.confidenceScore,
          sourceFromChatbot: _ticket.sourceFromChatbot,
          messages: _ticket.messages,
          kbArticleId: articleId.isEmpty ? _ticket.kbArticleId : articleId,
          kbConversionStatus: status,
        );
      });
      if (mounted) {
        final isAdmin = AuthScope.of(context).role == 'admin';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              isAdmin
                  ? 'Draft FAQ saved. Open it in Article Library to review and publish.'
                  : 'Draft FAQ saved. An admin must publish it for the chatbot and public KB.',
            ),
          ),
        );
      }
    } catch (error) {
      setState(() => _error = _friendlyError(error));
    } finally {
      titleCtrl.dispose();
      contentCtrl.dispose();
      if (mounted) setState(() => _saving = false);
    }
  }
}

class _AdminKbBadge extends StatelessWidget {
  final String label;
  final Color color;

  const _AdminKbBadge({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontWeight: FontWeight.w800,
          fontSize: 12,
        ),
      ),
    );
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
  final IconData? icon;
  final String message;

  const _AdminNotice({this.icon, required this.message});

  @override
  Widget build(BuildContext context) {
    final leading = icon;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: StudentPanel(
        shadow: false,
        child: leading == null
            ? Text(
                message,
                style: const TextStyle(
                  color: DesignTokens.muted,
                  height: 1.35,
                  fontWeight: FontWeight.w700,
                ),
              )
            : Row(
                children: [
                  Icon(leading, color: DesignTokens.maroon),
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
  final bool isInternal;

  const _AdminTicketMessage({
    required this.id,
    required this.ticketId,
    required this.senderId,
    required this.senderRole,
    required this.senderName,
    required this.message,
    required this.createdAt,
    this.isInternal = false,
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
      isInternal: json['is_internal'] == true,
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
  final List<_AdminTicketAttachment> attachments;
  final String? kbArticleId;
  final String kbConversionStatus;

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
    this.attachments = const [],
    this.kbArticleId,
    this.kbConversionStatus = 'none',
  });

  factory _AdminTicketEntry.fromJson(Map<String, dynamic> json) {
    final rawMessages =
        json['messages'] is List ? json['messages'] as List : const <dynamic>[];
    final rawAttachments = json['attachments'] is List
        ? json['attachments'] as List
        : const <dynamic>[];
    return _AdminTicketEntry(
      id: (json['ticket_id'] ?? json['id'] ?? '').toString(),
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
      assignedOffice: (json['assigned_office_name'] ?? json['assigned_office'] ?? 'Support Office')
          .toString(),
      priority: _adminTitlePriority((json['priority'] ?? 'Low').toString()),
      description: (json['description'] ?? '').toString(),
      confidenceScore: _parseDouble(json['confidence_score']),
      sourceFromChatbot: json['source_from_chatbot'] == true,
      messages: rawMessages
          .whereType<Map>()
          .map((item) =>
              _AdminTicketMessage.fromJson(Map<String, dynamic>.from(item)))
          .toList(),
      attachments: rawAttachments
          .whereType<Map>()
          .map((item) =>
              _AdminTicketAttachment.fromJson(Map<String, dynamic>.from(item)))
          .toList(),
      kbArticleId: _nullableAdminString(json['kb_article_id']),
      kbConversionStatus:
          (json['kb_conversion_status'] ?? 'none').toString().toLowerCase(),
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

  _RequesterProfile get requesterProfile =>
      _RequesterProfile.fromTicketText('$description\n$subject');
}

class _RequesterProfile {
  final String? studentNumber;
  final String? campus;
  final String? program;

  const _RequesterProfile({this.studentNumber, this.campus, this.program});

  factory _RequesterProfile.fromTicketText(String text) {
    String? capture(List<String> labels) {
      for (final label in labels) {
        final match = RegExp(
          '$label\\s*[:\\-]\\s*(.+?)(?=\\s*(?:Student number|Student No|Student ID|Campus|Program|Course)\\s*[:\\-]|\$)',
          caseSensitive: false,
          dotAll: true,
        ).firstMatch(text);
        var value = match?.group(1)?.split(RegExp(r'[\n|]')).first.trim();
        if (value != null && value.endsWith('.')) {
          value = value.substring(0, value.length - 1).trim();
        }
        if (value != null && value.isNotEmpty) return value;
      }
      return null;
    }

    return _RequesterProfile(
      studentNumber: capture(const ['Student number', 'Student No', 'Student ID']),
      campus: capture(const ['Campus']),
      program: capture(const ['Program', 'Course']),
    );
  }
}

class _AdminTicketAttachment {
  final String id;
  final String ticketId;
  final String originalFilename;
  final String contentType;
  final int sizeBytes;
  final String downloadUrl;
  final DateTime createdAt;

  const _AdminTicketAttachment({
    required this.id,
    required this.ticketId,
    required this.originalFilename,
    required this.contentType,
    required this.sizeBytes,
    required this.downloadUrl,
    required this.createdAt,
  });

  factory _AdminTicketAttachment.fromJson(Map<String, dynamic> json) {
    return _AdminTicketAttachment(
      id: (json['id'] ?? '').toString(),
      ticketId: (json['ticket_id'] ?? '').toString(),
      originalFilename: (json['original_filename'] ?? 'file').toString(),
      contentType: (json['content_type'] ?? '').toString(),
      sizeBytes: int.tryParse((json['size_bytes'] ?? '0').toString()) ?? 0,
      downloadUrl: (json['download_url'] ?? '').toString(),
      createdAt: _adminParseDate(json['created_at']),
    );
  }

  bool get isImage => contentType.toLowerCase().startsWith('image/');
}

class _TicketStats {
  final int total;
  final int open;
  final int inProgress;
  final int resolved;
  final int closed;
  final int highPriority;
  final Map<String, int> byOffice;
  final Map<String, int> byPriority;
  final Map<String, int> byCategory;

  const _TicketStats({
    required this.total,
    required this.open,
    required this.inProgress,
    required this.resolved,
    required this.closed,
    required this.highPriority,
    required this.byOffice,
    required this.byPriority,
    required this.byCategory,
  });

  String get totalText => total.toString();
  String get openText => open.toString();
  String get inProgressText => inProgress.toString();
  String get resolvedText => resolved.toString();
  String get closedText => closed.toString();
  String get highPriorityText => highPriority.toString();
  String get officeCountText => byOffice.length.toString();

  List<MapEntry<String, int>> get sortedOfficeEntries =>
      byOffice.entries.toList()
        ..sort((a, b) => b.value != a.value
            ? b.value.compareTo(a.value)
            : a.key.compareTo(b.key));

  List<MapEntry<String, int>> get sortedPriorityEntries {
    const order = ['Urgent', 'High', 'Medium', 'Low'];
    final entries = byPriority.entries.toList();
    entries.sort((a, b) {
      final ai = order.indexOf(a.key);
      final bi = order.indexOf(b.key);
      final av = ai < 0 ? 99 : ai;
      final bv = bi < 0 ? 99 : bi;
      if (av != bv) return av.compareTo(bv);
      return b.value.compareTo(a.value);
    });
    return entries;
  }

  List<MapEntry<String, int>> get sortedCategoryEntries =>
      byCategory.entries.toList()
        ..sort((a, b) => b.value != a.value
            ? b.value.compareTo(a.value)
            : a.key.compareTo(b.key));

  String toReportText() {
    final buffer = StringBuffer()
      ..writeln('ASKa-Piyu Ticket Report')
      ..writeln('Generated: ${DateTime.now().toIso8601String()}')
      ..writeln()
      ..writeln('Totals')
      ..writeln('- Total: $total')
      ..writeln('- Open: $open')
      ..writeln('- In Progress: $inProgress')
      ..writeln('- Resolved: $resolved')
      ..writeln('- Closed: $closed')
      ..writeln('- High/Urgent open: $highPriority')
      ..writeln()
      ..writeln('By office');
    for (final entry in sortedOfficeEntries) {
      buffer.writeln('- ${entry.key}: ${entry.value}');
    }
    buffer.writeln();
    buffer.writeln('By priority');
    for (final entry in sortedPriorityEntries) {
      buffer.writeln('- ${entry.key}: ${entry.value}');
    }
    buffer.writeln();
    buffer.writeln('By category');
    for (final entry in sortedCategoryEntries) {
      buffer.writeln('- ${entry.key}: ${entry.value}');
    }
    return buffer.toString();
  }

  factory _TicketStats.fromJson(Map<String, dynamic> json) {
    Map<String, int> readMap(Object? raw) {
      if (raw is! Map) return {};
      return {
        for (final entry in raw.entries)
          entry.key.toString(): _readInt(entry.value),
      };
    }

    return _TicketStats(
      total: _readInt(json['total']),
      open: _readInt(json['open']),
      inProgress: _readInt(json['in_progress']),
      resolved: _readInt(json['resolved']),
      closed: _readInt(json['closed']),
      highPriority: _readInt(json['high_priority']),
      byOffice: readMap(json['by_office']),
      byPriority: readMap(json['by_priority']),
      byCategory: readMap(json['by_category']),
    );
  }
}

Future<_TicketStats> _loadTicketStats(BuildContext context) async {
  final result = await ApiClient.send(
    method: 'GET',
    url: '${AppConfig.resolvedApiBase}/tickets/statistics',
    headers: AuthScope.of(context).ticketHeaders(),
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not load ticket statistics.'));
  }
  return _TicketStats.fromJson(data);
}

Future<List<_AdminUserEntry>> _loadAdminUsers(
  BuildContext context, {
  String? role,
}) async {
  final params = <String, String>{
    if (role != null && role.trim().isNotEmpty) 'role': role.trim().toLowerCase(),
  };
  final query = params.isEmpty ? '' : '?${Uri(queryParameters: params).query}';
  final result = await ApiClient.send(
    method: 'GET',
    url: '${AppConfig.resolvedApiBase}/auth/users$query',
    headers: AuthScope.of(context).ticketHeaders(),
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not load users.'));
  }
  final items = data['items'] is List ? data['items'] as List : const [];
  return items
      .whereType<Map>()
      .map((item) => _AdminUserEntry.fromJson(Map<String, dynamic>.from(item)))
      .toList();
}

Future<List<_AdminOfficeEntry>> _loadAdminOffices(BuildContext context) async {
  final result = await ApiClient.send(
    method: 'GET',
    url: '${AppConfig.resolvedApiBase}/tickets/offices',
    headers: AuthScope.of(context).ticketHeaders(),
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not load offices.'));
  }
  final items = data['items'] is List ? data['items'] as List : const [];
  return items
      .whereType<Map>()
      .map((item) => _AdminOfficeEntry.fromJson(Map<String, dynamic>.from(item)))
      .toList();
}

Future<_AdminUserEntry> _createOfficeStaffAccountRequest(
  BuildContext context, {
  required String fullName,
  required String email,
  required String password,
}) async {
  final result = await ApiClient.send(
    method: 'POST',
    url: '${AppConfig.resolvedApiBase}/auth/office-accounts',
    headers: {...AuthScope.of(context).ticketHeaders()},
    jsonBody: {
      'full_name': fullName,
      'email': email,
      'password': password,
    },
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(
      _extractError(data, 'Could not create office staff login.'),
    );
  }
  return _AdminUserEntry.fromJson(data);
}

Future<_AdminUserEntry> _createOfficeAccountRequest(
  BuildContext context, {
  required String fullName,
  required String email,
  required String password,
  required String officeId,
}) async {
  final result = await ApiClient.send(
    method: 'POST',
    url: '${AppConfig.resolvedApiBase}/auth/office-accounts',
    headers: {...AuthScope.of(context).ticketHeaders()},
    jsonBody: {
      'full_name': fullName,
      'email': email,
      'password': password,
      'office_id': officeId,
    },
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not create office account.'));
  }
  return _AdminUserEntry.fromJson(data);
}

Future<void> _deleteOfficeAccountRequest(
  BuildContext context, {
  required String userId,
}) async {
  final result = await ApiClient.send(
    method: 'DELETE',
    url: '${AppConfig.resolvedApiBase}/auth/users/$userId',
    headers: {...AuthScope.of(context).ticketHeaders()},
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not delete office account.'));
  }
}

Future<_AdminUserEntry> _setUserActiveRequest(
  BuildContext context, {
  required String userId,
  required bool isActive,
}) async {
  final result = await ApiClient.send(
    method: 'PATCH',
    url: '${AppConfig.resolvedApiBase}/auth/users/$userId/active',
    headers: {...AuthScope.of(context).ticketHeaders()},
    jsonBody: {'is_active': isActive},
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not update account status.'));
  }
  return _AdminUserEntry.fromJson(data);
}

Future<_AdminUserEntry> _resetUserPasswordRequest(
  BuildContext context, {
  required String userId,
  required String newPassword,
}) async {
  final result = await ApiClient.send(
    method: 'POST',
    url: '${AppConfig.resolvedApiBase}/auth/users/$userId/reset-password',
    headers: {...AuthScope.of(context).ticketHeaders()},
    jsonBody: {'new_password': newPassword},
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not reset password.'));
  }
  return _AdminUserEntry.fromJson(data);
}

Future<_AdminUserEntry> _createFacultyAccountRequest(
  BuildContext context, {
  required String fullName,
  required String email,
  required String password,
}) async {
  final result = await ApiClient.send(
    method: 'POST',
    url: '${AppConfig.resolvedApiBase}/auth/faculty-accounts',
    headers: {...AuthScope.of(context).ticketHeaders()},
    jsonBody: {
      'full_name': fullName,
      'email': email,
      'password': password,
    },
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not create faculty account.'));
  }
  return _AdminUserEntry.fromJson(data);
}

Future<_AdminOfficeEntry> _createOfficeRequest(
  BuildContext context, {
  required String name,
  String serviceCategory = '',
  String description = '',
}) async {
  final result = await ApiClient.send(
    method: 'POST',
    url: '${AppConfig.resolvedApiBase}/tickets/offices',
    headers: {...AuthScope.of(context).ticketHeaders()},
    jsonBody: {
      'name': name,
      if (serviceCategory.trim().isNotEmpty)
        'service_category': serviceCategory.trim(),
      if (description.trim().isNotEmpty) 'description': description.trim(),
    },
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not create office.'));
  }
  return _AdminOfficeEntry.fromJson(data);
}

Future<void> _deleteOfficeRequest(
  BuildContext context, {
  required String officeId,
}) async {
  final result = await ApiClient.send(
    method: 'DELETE',
    url: '${AppConfig.resolvedApiBase}/tickets/offices/$officeId',
    headers: {...AuthScope.of(context).ticketHeaders()},
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not delete office.'));
  }
}

class _AdminUserEntry {
  final String id;
  final String email;
  final String fullName;
  final String role;
  final String? officeId;
  final String? officeName;
  final bool isActive;
  final DateTime? createdAt;

  const _AdminUserEntry({
    required this.id,
    required this.email,
    required this.fullName,
    required this.role,
    this.officeId,
    this.officeName,
    this.isActive = true,
    this.createdAt,
  });

  factory _AdminUserEntry.fromJson(Map<String, dynamic> json) {
    return _AdminUserEntry(
      id: (json['id'] ?? '').toString(),
      email: (json['email'] ?? '').toString(),
      fullName: (json['full_name'] ?? '').toString(),
      role: (json['role'] ?? '').toString().toLowerCase(),
      officeId: (json['office_id'] ?? '').toString().trim().isEmpty
          ? null
          : (json['office_id'] ?? '').toString().trim(),
      officeName: (json['office_name'] ?? '').toString().trim().isEmpty
          ? null
          : (json['office_name'] ?? '').toString().trim(),
      isActive: json['is_active'] != false,
      createdAt: _adminParseNullableDate(json['created_at']),
    );
  }

  _AdminUserEntry copyWith({
    String? email,
    String? fullName,
    String? role,
    String? officeId,
    String? officeName,
    bool? isActive,
    DateTime? createdAt,
    bool clearOffice = false,
  }) {
    return _AdminUserEntry(
      id: id,
      email: email ?? this.email,
      fullName: fullName ?? this.fullName,
      role: role ?? this.role,
      officeId: clearOffice ? null : (officeId ?? this.officeId),
      officeName: clearOffice ? null : (officeName ?? this.officeName),
      isActive: isActive ?? this.isActive,
      createdAt: createdAt ?? this.createdAt,
    );
  }

  bool matchesNameOrEmail(String query) {
    final needle = query.trim().toLowerCase();
    if (needle.isEmpty) return true;
    return fullName.toLowerCase().contains(needle) ||
        email.toLowerCase().contains(needle);
  }
}

class _AdminOfficeEntry {
  final String id;
  final String name;
  final String? serviceCategory;

  const _AdminOfficeEntry({
    required this.id,
    required this.name,
    this.serviceCategory,
  });

  factory _AdminOfficeEntry.fromJson(Map<String, dynamic> json) {
    final category = (json['service_category'] ?? '').toString().trim();
    return _AdminOfficeEntry(
      id: (json['id'] ?? '').toString(),
      name: (json['name'] ?? '').toString(),
      serviceCategory: category.isEmpty ? null : category,
    );
  }
}

String? _officeAssignmentError(BuildContext context) {
  final user = AuthScope.of(context).currentUser;
  if (user?.role.trim().toLowerCase() != 'office') return null;
  final officeName = user?.officeName?.trim() ?? '';
  if (officeName.isEmpty) {
    return 'Your office account is not assigned to an office. Please contact the administrator.';
  }
  return null;
}

Future<List<_AdminTicketEntry>> _loadOfficeTickets(BuildContext context) async {
  final officeName =
      AuthScope.of(context).currentUser?.officeName?.trim() ?? '';
  final result = await ApiClient.send(
    method: 'GET',
    url: '${AppConfig.resolvedApiBase}/tickets',
    headers: AuthScope.of(context).ticketHeaders(),
  );
  final data = _decodeObject(result.body);
  final statusCode = result.statusCode;
  if (statusCode < 200 || statusCode >= 300) {
    throw StateError(_extractError(data, 'Could not load assigned tickets.'));
  }
  final items = data['items'] is List ? data['items'] as List : const [];
  return items
      .whereType<Map>()
      .map((item) => _AdminTicketEntry.fromJson(Map<String, dynamic>.from(item)))
      .where((ticket) => _adminSame(ticket.assignedOffice, officeName))
      .toList();
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
  IconData? icon,
}) {
  return InputDecoration(
    hintText: hintText,
    prefixIcon: icon == null ? null : Icon(icon, size: 20),
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

bool _adminSame(String left, String right) {
  return left.trim().toLowerCase() == right.trim().toLowerCase();
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

String _adminFormatAssignedDate(DateTime date) {
  final local = date.toLocal();
  return '${_adminFormatDate(local)}, ${local.year}';
}

String _officeDashboardDateLine(DateTime date) {
  const weekdays = [
    'Monday',
    'Tuesday',
    'Wednesday',
    'Thursday',
    'Friday',
    'Saturday',
    'Sunday',
  ];
  return '${weekdays[date.weekday - 1]}, ${_adminFormatDate(date)}, ${date.year}';
}

String _officeDashboardTimeLine(DateTime date) {
  final hour = date.hour == 0
      ? 12
      : date.hour > 12
          ? date.hour - 12
          : date.hour;
  final minute = date.minute.toString().padLeft(2, '0');
  final meridiem = date.hour >= 12 ? 'PM' : 'AM';
  return '$hour:$minute $meridiem';
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
