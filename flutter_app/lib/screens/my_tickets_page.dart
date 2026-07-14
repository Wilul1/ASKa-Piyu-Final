import 'dart:convert';
import 'dart:html' as html;

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../screens/login_page.dart';
import '../widgets/sidebar.dart';
import '../widgets/student_ui.dart';

const _statusOptions = ['All', 'Open', 'In Progress', 'Resolved', 'Closed'];
const _priorityOptions = ['All', 'Low', 'Medium', 'High', 'Urgent'];

class TicketMessage {
  final String id;
  final String ticketId;
  final String senderId;
  final String senderRole;
  final String senderName;
  final String message;
  final DateTime createdAt;

  const TicketMessage({
    required this.id,
    required this.ticketId,
    required this.senderId,
    required this.senderRole,
    required this.senderName,
    required this.message,
    required this.createdAt,
  });

  factory TicketMessage.fromJson(Map<String, dynamic> json) {
    return TicketMessage(
      id: (json['id'] ?? '').toString(),
      ticketId: (json['ticket_id'] ?? '').toString(),
      senderId: (json['sender_id'] ?? '').toString(),
      senderRole: (json['sender_role'] ?? 'office').toString(),
      senderName: (json['sender_name'] ?? 'Office').toString(),
      message: (json['message'] ?? '').toString(),
      createdAt: _parseDate(json['created_at']),
    );
  }
}

class TicketEntry {
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
  final List<TicketMessage> messages;

  const TicketEntry({
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

  factory TicketEntry.fromJson(Map<String, dynamic> json) {
    final rawMessages =
        json['messages'] is List ? json['messages'] as List : const <dynamic>[];
    return TicketEntry(
      id: (json['id'] ?? '').toString(),
      userId: (json['user_id'] ?? '').toString(),
      userName: (json['user_name'] ?? 'Student').toString(),
      userEmail: _nullableString(json['user_email']),
      subject: (json['original_question'] ?? 'Untitled concern').toString(),
      status: _titleStatus((json['status'] ?? 'Open').toString()),
      createdAt: _parseDate(json['created_at']),
      updatedAt: _parseDate(json['updated_at']),
      resolvedAt: _parseNullableDate(json['resolved_at']),
      closedAt: _parseNullableDate(json['closed_at']),
      category: (json['category'] ?? 'General').toString(),
      assignedOffice: (json['assigned_office'] ?? 'Support Office').toString(),
      priority: _titlePriority((json['priority'] ?? 'Low').toString()),
      description: (json['description'] ?? '').toString(),
      confidenceScore: _parseDouble(json['confidence_score']),
      sourceFromChatbot: json['source_from_chatbot'] == true,
      messages: rawMessages
          .whereType<Map>()
          .map((item) => TicketMessage.fromJson(
                Map<String, dynamic>.from(item),
              ))
          .toList(),
    );
  }

  bool matches(String query, String statusFilter, String priorityFilter) {
    final normalized = query.trim().toLowerCase();
    final matchesQuery = normalized.isEmpty ||
        id.toLowerCase().contains(normalized) ||
        subject.toLowerCase().contains(normalized) ||
        assignedOffice.toLowerCase().contains(normalized) ||
        category.toLowerCase().contains(normalized);
    final matchesStatus = statusFilter == 'All' || status == statusFilter;
    final matchesPriority =
        priorityFilter == 'All' || priority == priorityFilter;
    return matchesQuery && matchesStatus && matchesPriority;
  }
}

class MyTicketsPage extends StatefulWidget {
  final int initialTab;
  final String? initialQuestion;

  const MyTicketsPage({super.key, this.initialTab = 0, this.initialQuestion});

  @override
  State<MyTicketsPage> createState() => _MyTicketsPageState();
}

class _MyTicketsPageState extends State<MyTicketsPage>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  final List<TicketEntry> _tickets = [];
  final TextEditingController _searchCtrl = TextEditingController();
  bool _loading = false;
  String? _error;
  String _statusFilter = 'All';
  String _priorityFilter = 'All';
  bool _requestedInitialLoad = false;

  @override
  void initState() {
    super.initState();
    _tabController =
        TabController(length: 2, vsync: this, initialIndex: widget.initialTab);
    _searchCtrl.addListener(() => setState(() {}));
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    if (auth.isAuthenticated && !_requestedInitialLoad) {
      _requestedInitialLoad = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _loadTickets();
        }
      });
    }
  }

  @override
  void dispose() {
    _tabController.dispose();
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
          ..addAll(items.whereType<Map>().map(
                (item) => TicketEntry.fromJson(
                  Map<String, dynamic>.from(item),
                ),
              ));
      });
    } catch (error) {
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
  }

  void _ticketCreated(TicketEntry ticket) {
    setState(() {
      _tickets.insert(0, ticket);
      _statusFilter = 'All';
      _priorityFilter = 'All';
      _searchCtrl.clear();
      _tabController.animateTo(0);
    });
    _loadTickets();
  }

  void _openTicketDetails(TicketEntry ticket) {
    showDialog<void>(
      context: context,
      builder: (context) => TicketDetailsDialog(ticket: ticket),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    if (auth.isLoading) {
      return const Scaffold(
        backgroundColor: DesignTokens.bgGrey,
        body: Center(
          child: CircularProgressIndicator(color: DesignTokens.maroon),
        ),
      );
    }

    if (!auth.isAuthenticated) {
      return _LoginRequiredPage(
        current: widget.initialTab == 1
            ? StudentNavItem.submitTicket
            : StudentNavItem.myTickets,
        returnTo: (_) => MyTicketsPage(
          initialTab: widget.initialTab,
          initialQuestion: widget.initialQuestion,
        ),
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 900;
        final current = widget.initialTab == 1
            ? StudentNavItem.submitTicket
            : StudentNavItem.myTickets;
        final filteredTickets = _tickets
            .where((ticket) => ticket.matches(
                  _searchCtrl.text,
                  _statusFilter,
                  _priorityFilter,
                ))
            .toList();

        final bodyContent = StudentPage(
          maxWidth: 1120,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              HeaderRow(isWide: isWide),
              const SizedBox(height: 18),
              TabsRow(tabController: _tabController),
              const SizedBox(height: 18),
              SizedBox(
                height: isWide ? 760 : 840,
                child: TabBarView(
                  controller: _tabController,
                  children: [
                    RefreshIndicator(
                      onRefresh: _loadTickets,
                      color: DesignTokens.maroon,
                      child: SingleChildScrollView(
                        physics: const AlwaysScrollableScrollPhysics(),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            StatsCards(tickets: _tickets),
                            const SizedBox(height: 18),
                            TicketFilters(
                              searchCtrl: _searchCtrl,
                              statusFilter: _statusFilter,
                              priorityFilter: _priorityFilter,
                              onStatusChanged: (value) =>
                                  setState(() => _statusFilter = value),
                              onPriorityChanged: (value) =>
                                  setState(() => _priorityFilter = value),
                              onRefresh: _loadTickets,
                              isRefreshing: _loading,
                            ),
                            const SizedBox(height: 16),
                            if (_loading && _tickets.isEmpty)
                              const TicketLoadingState()
                            else if (_error != null)
                              _TicketError(
                                  message: _error!, onRetry: _loadTickets)
                            else
                              TicketsList(
                                tickets: filteredTickets,
                                hasAnyTickets: _tickets.isNotEmpty,
                                onTicketTap: _openTicketDetails,
                              ),
                          ],
                        ),
                      ),
                    ),
                    SingleChildScrollView(
                      child: CreateTicketForm(
                        initialQuestion: widget.initialQuestion,
                        onCreated: _ticketCreated,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        );

        if (isWide) {
          return Scaffold(
            backgroundColor: DesignTokens.bgGrey,
            body: Row(
              children: [
                SizedBox(width: 220, child: AppSidebar(current: current)),
                Expanded(child: bodyContent),
              ],
            ),
          );
        }

        return Scaffold(
          backgroundColor: DesignTokens.bgGrey,
          drawer: Drawer(child: AppSidebar(current: current)),
          appBar: AppBar(
            title:
                Text(widget.initialTab == 1 ? 'Submit Ticket' : 'My Tickets'),
          ),
          body: bodyContent,
        );
      },
    );
  }
}

class HeaderRow extends StatelessWidget {
  final bool isWide;
  const HeaderRow({required this.isWide});

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      padding: const EdgeInsets.fromLTRB(22, 20, 22, 20),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StudentIconBox(
            icon: Icons.support_agent_rounded,
            color: DesignTokens.maroon,
            size: 48,
          ),
          const SizedBox(width: 14),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Student Tickets',
                  style: TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.w900,
                    color: DesignTokens.ink,
                  ),
                ),
                SizedBox(height: 6),
                Text(
                  'Create support requests, track progress, and read office replies in one place.',
                  style: TextStyle(fontSize: 14, color: DesignTokens.muted),
                ),
              ],
            ),
          ),
          if (isWide)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: DesignTokens.maroon.withOpacity(0.08),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(
                  color: DesignTokens.maroon.withOpacity(0.14),
                ),
              ),
              child: const Text(
                'Support Center',
                style: TextStyle(
                  color: DesignTokens.maroon,
                  fontWeight: FontWeight.w800,
                  fontSize: 12,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _LoginRequiredPage extends StatelessWidget {
  final StudentNavItem current;
  final WidgetBuilder returnTo;

  const _LoginRequiredPage({
    required this.current,
    required this.returnTo,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 900;
        final content = StudentPage(
          maxWidth: 620,
          child: StudentPanel(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const StudentIconBox(
                  icon: Icons.lock_person_rounded,
                  color: DesignTokens.maroon,
                  size: 56,
                ),
                const SizedBox(height: 18),
                const Text(
                  'Login required',
                  style: TextStyle(
                    color: DesignTokens.ink,
                    fontSize: 26,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  loginRequiredMessage,
                  style: TextStyle(color: DesignTokens.muted, height: 1.45),
                ),
                const SizedBox(height: 22),
                ElevatedButton(
                  onPressed: () => Navigator.of(context).pushReplacement(
                    MaterialPageRoute(
                      builder: (_) => LoginPage(
                        returnTo: returnTo,
                        message: loginRequiredMessage,
                      ),
                    ),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: DesignTokens.maroon,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(vertical: 15),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                  ),
                  child: const Text('Login or Create Account'),
                ),
              ],
            ),
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
          appBar: AppBar(title: const Text('Login Required')),
          body: content,
        );
      },
    );
  }
}

class TabsRow extends StatelessWidget {
  final TabController tabController;
  const TabsRow({required this.tabController});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: DesignTokens.border),
      ),
      child: TabBar(
        controller: tabController,
        labelColor: Colors.white,
        unselectedLabelColor: DesignTokens.muted,
        indicator: BoxDecoration(
          color: DesignTokens.maroon,
          borderRadius: BorderRadius.circular(14),
        ),
        indicatorPadding: const EdgeInsets.all(4),
        labelStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800),
        unselectedLabelStyle:
            const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
        tabs: const [
          Tab(icon: Icon(Icons.fact_check_rounded), text: 'My Tickets'),
          Tab(icon: Icon(Icons.add_task_rounded), text: 'Submit Ticket'),
        ],
      ),
    );
  }
}

class StatsCards extends StatelessWidget {
  final List<TicketEntry> tickets;
  const StatsCards({super.key, required this.tickets});

  @override
  Widget build(BuildContext context) {
    final openCount = tickets.where((t) => t.status == 'Open').length;
    final progressCount =
        tickets.where((t) => t.status == 'In Progress').length;
    final closedCount = tickets.where((t) => t.status == 'Closed').length;
    final totalCount = tickets.length;

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
            StatCard(
              number: '$openCount',
              label: 'Open',
              accent: const Color(0xFF2563EB),
              icon: Icons.mark_email_unread_outlined,
            ),
            StatCard(
              number: '$progressCount',
              label: 'In Progress',
              accent: const Color(0xFFF97316),
              icon: Icons.sync_rounded,
            ),
            StatCard(
              number: '$closedCount',
              label: 'Closed',
              accent: const Color(0xFF16A34A),
              icon: Icons.check_circle_outline_rounded,
            ),
            StatCard(
              number: '$totalCount',
              label: 'Total',
              accent: DesignTokens.maroon,
              icon: Icons.confirmation_num_outlined,
            ),
          ],
        );
      },
    );
  }
}

class StatCard extends StatelessWidget {
  final String number;
  final String label;
  final Color accent;
  final IconData icon;

  const StatCard({
    super.key,
    required this.number,
    required this.label,
    required this.accent,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 104,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: DesignTokens.softShadow(0.04),
        border: Border.all(color: DesignTokens.border),
      ),
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          StudentIconBox(icon: icon, color: accent, size: 42),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  number,
                  style: TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.w900,
                    color: accent,
                    height: 1,
                  ),
                ),
                const SizedBox(height: 7),
                Text(
                  label,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 13,
                    color: DesignTokens.muted,
                    fontWeight: FontWeight.w700,
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

class TicketFilters extends StatelessWidget {
  final TextEditingController searchCtrl;
  final String statusFilter;
  final String priorityFilter;
  final ValueChanged<String> onStatusChanged;
  final ValueChanged<String> onPriorityChanged;
  final Future<void> Function() onRefresh;
  final bool isRefreshing;

  const TicketFilters({
    super.key,
    required this.searchCtrl,
    required this.statusFilter,
    required this.priorityFilter,
    required this.onStatusChanged,
    required this.onPriorityChanged,
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
          final isNarrow = constraints.maxWidth < 720;
          final searchField = TextField(
            controller: searchCtrl,
            decoration: _inputDecoration(
              hintText: 'Search ticket ID, subject, office, or category',
              icon: Icons.search_rounded,
            ),
          );
          final filters = [
            Expanded(
              child: _FilterDropdown(
                label: 'Status',
                value: statusFilter,
                values: _statusOptions,
                onChanged: onStatusChanged,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _FilterDropdown(
                label: 'Priority',
                value: priorityFilter,
                values: _priorityOptions,
                onChanged: onPriorityChanged,
              ),
            ),
            const SizedBox(width: 12),
            Tooltip(
              message: 'Refresh tickets',
              child: Container(
                decoration: BoxDecoration(
                  color: DesignTokens.maroon.withOpacity(0.08),
                  borderRadius: BorderRadius.circular(14),
                ),
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
              ),
            ),
          ];

          if (isNarrow) {
            return Column(
              children: [
                searchField,
                const SizedBox(height: 12),
                Row(children: filters),
              ],
            );
          }

          return Row(
            children: [
              Expanded(flex: 3, child: searchField),
              const SizedBox(width: 12),
              ...filters,
            ],
          );
        },
      ),
    );
  }
}

class _FilterDropdown extends StatelessWidget {
  final String label;
  final String value;
  final List<String> values;
  final ValueChanged<String> onChanged;

  const _FilterDropdown({
    required this.label,
    required this.value,
    required this.values,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<String>(
      value: value,
      isExpanded: true,
      decoration: _inputDecoration(
        hintText: label,
        icon: label == 'Status'
            ? Icons.tune_rounded
            : Icons.priority_high_rounded,
      ),
      items: values
          .map((item) => DropdownMenuItem(value: item, child: Text(item)))
          .toList(),
      onChanged: (value) {
        if (value != null) onChanged(value);
      },
    );
  }
}

class TicketsList extends StatelessWidget {
  final List<TicketEntry> tickets;
  final bool hasAnyTickets;
  final ValueChanged<TicketEntry> onTicketTap;

  const TicketsList({
    super.key,
    required this.tickets,
    required this.hasAnyTickets,
    required this.onTicketTap,
  });

  @override
  Widget build(BuildContext context) {
    if (tickets.isEmpty) {
      return TicketEmptyState(
        icon:
            hasAnyTickets ? Icons.manage_search_rounded : Icons.inbox_outlined,
        title: hasAnyTickets ? 'No matching tickets' : 'No tickets yet',
        message: hasAnyTickets
            ? 'Try changing the search text, status, or priority filter.'
            : 'Submitted support requests will appear here with status updates and office replies.',
      );
    }

    return Column(
      children: tickets
          .map(
            (ticket) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child:
                  TicketCard(ticket: ticket, onTap: () => onTicketTap(ticket)),
            ),
          )
          .toList(),
    );
  }
}

class TicketCard extends StatelessWidget {
  final TicketEntry ticket;
  final VoidCallback onTap;

  const TicketCard({super.key, required this.ticket, required this.onTap});

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
                        TicketStatusChip(status: ticket.status),
                        TicketPriorityChip(priority: ticket.priority),
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
              _MetaItem(
                icon: Icons.apartment_rounded,
                label: ticket.assignedOffice,
              ),
              _MetaItem(
                icon: Icons.category_outlined,
                label: ticket.category,
              ),
              _MetaItem(
                icon: Icons.schedule_rounded,
                label: 'Updated ${_formatDate(ticket.updatedAt)}',
              ),
              _MetaItem(
                icon: Icons.forum_outlined,
                label: '${ticket.messages.length} replies',
              ),
            ],
          ),
          if (ticket.description.trim().isNotEmpty) ...[
            const SizedBox(height: 12),
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
    );
  }
}

class TicketDetailsDialog extends StatelessWidget {
  final TicketEntry ticket;

  const TicketDetailsDialog({super.key, required this.ticket});

  @override
  Widget build(BuildContext context) {
    final officeReplies = ticket.messages
        .where((message) => message.senderRole.toLowerCase() != 'student')
        .length;
    return Dialog(
      insetPadding: const EdgeInsets.all(18),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 860, maxHeight: 760),
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
                          ticket.id,
                          style: const TextStyle(
                            color: DesignTokens.maroon,
                            fontWeight: FontWeight.w900,
                            fontSize: 13,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          ticket.subject,
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
                    if (ticket.status == 'Resolved' ||
                        ticket.status == 'Closed') ...[
                      _TicketStatusBanner(status: ticket.status),
                      const SizedBox(height: 14),
                    ],
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        TicketStatusChip(status: ticket.status),
                        TicketPriorityChip(priority: ticket.priority),
                      ],
                    ),
                    const SizedBox(height: 18),
                    _DetailGrid(ticket: ticket),
                    const SizedBox(height: 20),
                    const _DialogSectionHeader(title: 'Description'),
                    const SizedBox(height: 8),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: const Color(0xFFF8FAFC),
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: DesignTokens.border),
                      ),
                      child: Text(
                        ticket.description.trim().isEmpty
                            ? 'No additional description provided.'
                            : ticket.description,
                        style: const TextStyle(
                          color: DesignTokens.ink,
                          height: 1.45,
                        ),
                      ),
                    ),
                    const SizedBox(height: 22),
                    _DialogSectionHeader(
                      title: 'Conversation',
                      trailing:
                          '$officeReplies office ${officeReplies == 1 ? 'reply' : 'replies'}',
                    ),
                    const SizedBox(height: 10),
                    ConversationTimeline(ticket: ticket),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TicketStatusBanner extends StatelessWidget {
  final String status;

  const _TicketStatusBanner({required this.status});

  @override
  Widget build(BuildContext context) {
    final isClosed = status == 'Closed';
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFECFDF5),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFF86EFAC)),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.check_circle_outline_rounded,
            color: Color(0xFF16A34A),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              isClosed
                  ? 'This ticket has been closed.'
                  : 'This ticket has been marked as resolved.',
              style: const TextStyle(
                color: Color(0xFF166534),
                fontWeight: FontWeight.w900,
                height: 1.3,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _DialogSectionHeader extends StatelessWidget {
  final String title;
  final String? trailing;

  const _DialogSectionHeader({required this.title, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(
            title,
            style: const TextStyle(
              fontWeight: FontWeight.w900,
              color: DesignTokens.ink,
              fontSize: 15,
            ),
          ),
        ),
        if (trailing != null)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: DesignTokens.maroon.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(
                color: DesignTokens.maroon.withValues(alpha: 0.14),
              ),
            ),
            child: Text(
              trailing!,
              style: const TextStyle(
                color: DesignTokens.maroon,
                fontWeight: FontWeight.w900,
                fontSize: 11,
              ),
            ),
          ),
      ],
    );
  }
}

class _DetailGrid extends StatelessWidget {
  final TicketEntry ticket;

  const _DetailGrid({required this.ticket});

  @override
  Widget build(BuildContext context) {
    final details = [
      _DetailData('Category', ticket.category, Icons.category_outlined),
      _DetailData(
          'Assigned office', ticket.assignedOffice, Icons.apartment_rounded),
      _DetailData('Created', _formatFullDate(ticket.createdAt),
          Icons.event_available_outlined),
      _DetailData(
          'Updated', _formatFullDate(ticket.updatedAt), Icons.update_rounded),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 620 ? 2 : 1;
        return StudentResponsiveWrap(
          columns: columns,
          spacing: 12,
          children: details
              .map(
                (detail) => Container(
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
                ),
              )
              .toList(),
        );
      },
    );
  }
}

class _DetailData {
  final String label;
  final String value;
  final IconData icon;

  const _DetailData(this.label, this.value, this.icon);
}

class ConversationTimeline extends StatelessWidget {
  final TicketEntry ticket;

  const ConversationTimeline({super.key, required this.ticket});

  @override
  Widget build(BuildContext context) {
    final replies = ticket.messages
        .where((message) => message.senderRole.toLowerCase() != 'student')
        .toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        StudentConcernBubble(ticket: ticket),
        const SizedBox(height: 14),
        if (replies.isEmpty)
          const _NoOfficeRepliesState()
        else
          ...replies.map(
            (message) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: OfficeReplyBubble(message: message),
            ),
          ),
      ],
    );
  }
}

class StudentConcernBubble extends StatelessWidget {
  final TicketEntry ticket;

  const StudentConcernBubble({super.key, required this.ticket});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFD7DEE9)),
        boxShadow: DesignTokens.softShadow(0.035),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: const Color(0xFFE2E8F0),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Icon(
                  Icons.person_outline_rounded,
                  color: DesignTokens.muted,
                  size: 19,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      ticket.userName.trim().isEmpty
                          ? 'Student concern'
                          : ticket.userName,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: DesignTokens.ink,
                        fontWeight: FontWeight.w900,
                        fontSize: 13,
                      ),
                    ),
                    const Text(
                      'Student concern',
                      style: TextStyle(
                        color: DesignTokens.muted,
                        fontWeight: FontWeight.w800,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
              Text(
                _formatDate(ticket.createdAt),
                style: const TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            ticket.subject,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w900,
              fontSize: 15,
              height: 1.35,
            ),
          ),
          if (ticket.description.trim().isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              ticket.description,
              style: const TextStyle(
                color: DesignTokens.ink,
                height: 1.45,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _NoOfficeRepliesState extends StatelessWidget {
  const _NoOfficeRepliesState();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.035),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StudentIconBox(
            icon: Icons.support_agent_rounded,
            color: DesignTokens.maroon,
            size: 38,
          ),
          SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'No office replies yet.',
                  style: TextStyle(
                    color: DesignTokens.ink,
                    fontWeight: FontWeight.w900,
                    fontSize: 14,
                  ),
                ),
                SizedBox(height: 4),
                Text(
                  'Your assigned office will respond here once they review your concern.',
                  style: TextStyle(
                    color: DesignTokens.muted,
                    height: 1.4,
                    fontWeight: FontWeight.w700,
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

class OfficeReplyBubble extends StatelessWidget {
  final TicketMessage message;

  const OfficeReplyBubble({super.key, required this.message});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 680),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFFFFF7ED),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: DesignTokens.maroon.withValues(alpha: 0.24),
          ),
          boxShadow: DesignTokens.softShadow(0.045),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                    color: DesignTokens.maroon.withValues(alpha: 0.10),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(
                    Icons.support_agent_rounded,
                    color: DesignTokens.maroon,
                    size: 19,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        message.senderName.trim().isEmpty
                            ? 'Assigned Office'
                            : message.senderName,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: DesignTokens.maroon,
                          fontWeight: FontWeight.w900,
                          fontSize: 13,
                        ),
                      ),
                      const Text(
                        'Office Reply',
                        style: TextStyle(
                          color: DesignTokens.muted,
                          fontWeight: FontWeight.w800,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.72),
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(
                      color: DesignTokens.maroon.withValues(alpha: 0.10),
                    ),
                  ),
                  child: Text(
                    _formatDate(message.createdAt),
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              message.message,
              style: const TextStyle(
                color: DesignTokens.ink,
                height: 1.5,
                fontSize: 14,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class MessageBubble extends StatelessWidget {
  final TicketMessage message;

  const MessageBubble({super.key, required this.message});

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
        constraints: const BoxConstraints(maxWidth: 620),
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
                      : Icons.business_center_outlined,
                  color: accent,
                  size: 18,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '${message.senderName} • ${_titleCase(message.senderRole)}',
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: accent,
                      fontWeight: FontWeight.w900,
                      fontSize: 12,
                    ),
                  ),
                ),
                Text(
                  _formatDate(message.createdAt),
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
              style: const TextStyle(
                color: DesignTokens.ink,
                height: 1.45,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class TicketStatusChip extends StatelessWidget {
  final String status;

  const TicketStatusChip({super.key, required this.status});

  @override
  Widget build(BuildContext context) {
    final style = _statusStyle(status);
    return _ChipPill(label: status, icon: style.icon, color: style.color);
  }
}

class TicketPriorityChip extends StatelessWidget {
  final String priority;

  const TicketPriorityChip({super.key, required this.priority});

  @override
  Widget build(BuildContext context) {
    final style = _priorityStyle(priority);
    return _ChipPill(label: priority, icon: style.icon, color: style.color);
  }
}

class _ChipPill extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color color;

  const _ChipPill({
    required this.label,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withOpacity(0.10),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withOpacity(0.18)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 5),
          Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w900,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

class TicketEmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String message;

  const TicketEmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
  });

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 42),
      shadow: false,
      child: Column(
        children: [
          StudentIconBox(icon: icon, color: DesignTokens.maroon, size: 52),
          const SizedBox(height: 14),
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
            style: const TextStyle(color: DesignTokens.muted, height: 1.35),
          ),
        ],
      ),
    );
  }
}

class TicketLoadingState extends StatelessWidget {
  const TicketLoadingState({super.key});

  @override
  Widget build(BuildContext context) {
    return const StudentPanel(
      padding: EdgeInsets.symmetric(vertical: 44),
      shadow: false,
      child: Center(
        child: CircularProgressIndicator(color: DesignTokens.maroon),
      ),
    );
  }
}

class _TicketError extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _TicketError({required this.message, required this.onRetry});

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

class CreateTicketForm extends StatefulWidget {
  final String? initialQuestion;
  final ValueChanged<TicketEntry> onCreated;

  const CreateTicketForm({
    super.key,
    this.initialQuestion,
    required this.onCreated,
  });

  @override
  State<CreateTicketForm> createState() => _CreateTicketFormState();
}

class _CreateTicketFormState extends State<CreateTicketForm> {
  final _formKey = GlobalKey<FormState>();
  final TextEditingController _subjectCtrl = TextEditingController();
  final TextEditingController _descCtrl = TextEditingController();
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _subjectCtrl.text = widget.initialQuestion ?? '';
  }

  @override
  void dispose() {
    _subjectCtrl.dispose();
    _descCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() => _submitting = true);
    try {
      final request = html.HttpRequest();
      request.open('POST', '${AppConfig.resolvedApiBase}/tickets');
      request.setRequestHeader('Content-Type', 'application/json');
      AuthScope.of(context).ticketHeaders().forEach(request.setRequestHeader);
      request.send(jsonEncode({
        'original_question': _subjectCtrl.text.trim(),
        'description': _descCtrl.text.trim(),
        'source_from_chatbot': widget.initialQuestion != null,
      }));
      await request.onLoadEnd.first;
      final data = _decodeObject(request.responseText);
      final statusCode = request.status ?? 0;
      if (statusCode < 200 || statusCode >= 300) {
        throw StateError(_extractError(data, 'Ticket submission failed.'));
      }
      final ticket = TicketEntry.fromJson(data);
      widget.onCreated(ticket);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text(
            'Ticket submitted to ${ticket.assignedOffice}.',
          ),
        ),
      );
      setState(() {
        _subjectCtrl.clear();
        _descCtrl.clear();
      });
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          backgroundColor: const Color(0xFF991B1B),
          content: Text(_friendlyError(error)),
        ),
      );
    } finally {
      if (mounted) {
        setState(() => _submitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      padding: const EdgeInsets.all(22),
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: const [
                StudentIconBox(
                  icon: Icons.add_task_rounded,
                  color: DesignTokens.maroon,
                  size: 46,
                ),
                SizedBox(width: 14),
                Expanded(
                  child: StudentSectionTitle(
                    title: 'Submit a Support Request',
                    subtitle:
                        'Describe your concern clearly so ASKa-Piyu can route it to the right office.',
                  ),
                ),
              ],
            ),
            const SizedBox(height: 22),
            _FieldLabel(
              label: 'Original question or concern',
              helper:
                  'Use the exact question or short concern you want the office to answer.',
            ),
            const SizedBox(height: 8),
            TextFormField(
              controller: _subjectCtrl,
              validator: (value) => (value == null || value.trim().isEmpty)
                  ? 'Please enter your original question or concern.'
                  : null,
              textInputAction: TextInputAction.next,
              decoration: _inputDecoration(
                hintText:
                    'Example: How can I request my transcript of records?',
                icon: Icons.subject_outlined,
              ),
            ),
            const SizedBox(height: 18),
            _FieldLabel(
              label: 'Description',
              helper:
                  'Add dates, transaction details, office visits, or steps you already tried.',
            ),
            const SizedBox(height: 8),
            TextFormField(
              controller: _descCtrl,
              validator: (value) => (value == null || value.trim().isEmpty)
                  ? 'Please describe your concern so the office has enough context.'
                  : null,
              minLines: 7,
              maxLines: 12,
              decoration: _inputDecoration(
                hintText: 'Tell us what happened and what help you need.',
                icon: Icons.description_outlined,
                alignIconTop: true,
              ),
            ),
            const SizedBox(height: 18),
            _AttachmentComingSoon(),
            const SizedBox(height: 22),
            LayoutBuilder(
              builder: (context, constraints) {
                final isNarrow = constraints.maxWidth < 520;
                final clearButton = OutlinedButton.icon(
                  onPressed: _submitting
                      ? null
                      : () {
                          _subjectCtrl.clear();
                          _descCtrl.clear();
                        },
                  icon: const Icon(Icons.clear_rounded),
                  label: const Text('Clear'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: DesignTokens.maroon,
                    side: const BorderSide(color: DesignTokens.border),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 18,
                      vertical: 15,
                    ),
                  ),
                );
                final submitButton = ElevatedButton.icon(
                  onPressed: _submitting ? null : _submit,
                  icon: _submitting
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.send_rounded),
                  label: Text(_submitting ? 'Submitting...' : 'Submit Ticket'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: DesignTokens.maroon,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 15,
                    ),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                  ),
                );

                if (isNarrow) {
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      submitButton,
                      const SizedBox(height: 10),
                      clearButton,
                    ],
                  );
                }

                return Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    clearButton,
                    const SizedBox(width: 12),
                    submitButton,
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _FieldLabel extends StatelessWidget {
  final String label;
  final String helper;

  const _FieldLabel({required this.label, required this.helper});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: DesignTokens.ink,
            fontWeight: FontWeight.w900,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          helper,
          style: const TextStyle(
            color: DesignTokens.muted,
            fontSize: 12,
            height: 1.35,
          ),
        ),
      ],
    );
  }
}

class _AttachmentComingSoon extends StatelessWidget {
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
      child: Row(
        children: const [
          StudentIconBox(
            icon: Icons.attach_file_rounded,
            color: DesignTokens.muted,
            size: 38,
          ),
          SizedBox(width: 12),
          Expanded(
            child: Text(
              'Attachment upload coming soon. You can submit the ticket without a file.',
              style: TextStyle(
                color: DesignTokens.muted,
                height: 1.35,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MetaItem extends StatelessWidget {
  final IconData icon;
  final String label;

  const _MetaItem({required this.icon, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 16, color: DesignTokens.muted),
        const SizedBox(width: 5),
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 240),
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

class _ChipStyle {
  final Color color;
  final IconData icon;

  const _ChipStyle(this.color, this.icon);
}

InputDecoration _inputDecoration({
  required String hintText,
  required IconData icon,
  bool alignIconTop = false,
}) {
  return InputDecoration(
    hintText: hintText,
    filled: true,
    fillColor: const Color(0xFFF8FAFC),
    prefixIcon: Padding(
      padding:
          alignIconTop ? const EdgeInsets.only(bottom: 86) : EdgeInsets.zero,
      child: Icon(icon, size: 20),
    ),
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
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
  );
}

_ChipStyle _statusStyle(String status) {
  switch (status) {
    case 'Open':
      return const _ChipStyle(
          Color(0xFF2563EB), Icons.mark_email_unread_outlined);
    case 'In Progress':
      return const _ChipStyle(Color(0xFFF97316), Icons.sync_rounded);
    case 'Resolved':
      return const _ChipStyle(Color(0xFF7C3AED), Icons.task_alt_rounded);
    case 'Closed':
      return const _ChipStyle(Color(0xFF16A34A), Icons.check_circle_outline);
    default:
      return const _ChipStyle(DesignTokens.muted, Icons.help_outline_rounded);
  }
}

_ChipStyle _priorityStyle(String priority) {
  switch (priority) {
    case 'Urgent':
      return const _ChipStyle(Color(0xFFDC2626), Icons.priority_high_rounded);
    case 'High':
      return const _ChipStyle(
          Color(0xFFEA580C), Icons.keyboard_double_arrow_up);
    case 'Medium':
      return const _ChipStyle(Color(0xFFD97706), Icons.remove_rounded);
    case 'Low':
      return const _ChipStyle(Color(0xFF0F766E), Icons.keyboard_arrow_down);
    default:
      return const _ChipStyle(DesignTokens.muted, Icons.flag_outlined);
  }
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
  final message = data['message'];
  if (message is String && message.trim().isNotEmpty) return message;
  return fallback;
}

String _friendlyError(Object error) {
  final text = error.toString().replaceFirst('Bad state: ', '').trim();
  return text.isEmpty ? 'Something went wrong. Please try again.' : text;
}

DateTime _parseDate(Object? value) {
  return _parseNullableDate(value) ?? DateTime.now();
}

DateTime? _parseNullableDate(Object? value) {
  final text = value?.toString().trim() ?? '';
  if (text.isEmpty || text == 'null') return null;
  return DateTime.tryParse(text)?.toLocal();
}

double? _parseDouble(Object? value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  return double.tryParse(value.toString());
}

String? _nullableString(Object? value) {
  final text = value?.toString().trim() ?? '';
  return text.isEmpty || text == 'null' ? null : text;
}

String _titleStatus(String value) {
  final normalized = value.trim().toLowerCase();
  if (normalized == 'in_progress' || normalized == 'in progress') {
    return 'In Progress';
  }
  if (normalized == 'resolved') return 'Resolved';
  if (normalized == 'closed') return 'Closed';
  return 'Open';
}

String _titlePriority(String value) {
  final normalized = value.trim().toLowerCase();
  if (normalized == 'urgent') return 'Urgent';
  if (normalized == 'high') return 'High';
  if (normalized == 'medium') return 'Medium';
  return 'Low';
}

String _titleCase(String value) {
  final text = value.trim();
  if (text.isEmpty) return '';
  return text[0].toUpperCase() + text.substring(1).toLowerCase();
}

String _formatDate(DateTime date) {
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
    'Dec'
  ];
  final hour = date.hour % 12 == 0 ? 12 : date.hour % 12;
  final minute = date.minute.toString().padLeft(2, '0');
  final ampm = date.hour >= 12 ? 'PM' : 'AM';
  return '${months[date.month - 1]} ${date.day}, $hour:$minute $ampm';
}

String _formatFullDate(DateTime date) {
  return '${_formatDate(date)}, ${date.year}';
}
