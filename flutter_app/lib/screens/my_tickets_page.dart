import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../app_config.dart';
import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../screens/login_page.dart';
import '../services/api_client.dart';
import '../services/download_file.dart';
import '../services/file_pick.dart';
import '../widgets/phone_layout.dart';
import '../widgets/public_site_header.dart';
import '../widgets/sidebar.dart';
import '../widgets/student_ui.dart';

const _statusOptions = ['All', 'Open', 'In Progress', 'Resolved', 'Closed'];

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
  final List<_TicketAttachment> attachments;

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
    this.attachments = const [],
  });

  factory TicketEntry.fromJson(Map<String, dynamic> json) {
    final rawMessages =
        json['messages'] is List ? json['messages'] as List : const <dynamic>[];
    final rawAttachments = json['attachments'] is List
        ? json['attachments'] as List
        : const <dynamic>[];
    return TicketEntry(
      id: (json['ticket_id'] ?? json['id'] ?? '').toString(),
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
      assignedOffice: (json['assigned_office_name'] ?? json['assigned_office'] ?? 'Support Office')
          .toString(),
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
      attachments: rawAttachments
          .whereType<Map>()
          .map((item) =>
              _TicketAttachment.fromJson(Map<String, dynamic>.from(item)))
          .toList(),
    );
  }

  bool matches(String query, String statusFilter) {
    final normalized = query.trim().toLowerCase();
    final matchesQuery = normalized.isEmpty ||
        id.toLowerCase().contains(normalized) ||
        subject.toLowerCase().contains(normalized) ||
        assignedOffice.toLowerCase().contains(normalized) ||
        category.toLowerCase().contains(normalized);
    final matchesStatus = statusFilter == 'All' || status == statusFilter;
    return matchesQuery && matchesStatus;
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
  final List<_TicketNotification> _notifications = [];
  final TextEditingController _searchCtrl = TextEditingController();
  bool _loading = false;
  String? _error;
  String _statusFilter = 'All';
  bool _requestedInitialLoad = false;
  int _unreadNotifications = 0;
  Timer? _listPollTimer;

  @override
  void initState() {
    super.initState();
    _tabController =
        TabController(length: 2, vsync: this, initialIndex: widget.initialTab);
    _searchCtrl.addListener(() => setState(() {}));
    _tabController.addListener(() {
      if (!_tabController.indexIsChanging) setState(() {});
    });
    _listPollTimer = Timer.periodic(const Duration(seconds: 8), (_) {
      if (!mounted || !AuthScope.of(context).isAuthenticated) return;
      if (_tabController.index != 0) return;
      _loadTickets(silent: true);
      _loadNotifications(silent: true);
    });
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
          _loadNotifications();
        }
      });
    }
  }

  @override
  void dispose() {
    _listPollTimer?.cancel();
    _tabController.dispose();
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadTickets({bool silent = false}) async {
    if (!silent) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
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
      if (!mounted) return;
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
      if (!silent && mounted) {
        setState(() => _error = _friendlyError(error));
      }
    } finally {
      if (mounted && !silent) {
        setState(() => _loading = false);
      }
    }
  }

  Future<void> _loadNotifications({bool silent = false}) async {
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/notifications',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      final data = _decodeObject(result.body);
      final statusCode = result.statusCode;
      if (statusCode < 200 || statusCode >= 300) return;
      final items = data['items'] is List ? data['items'] as List : const [];
      if (!mounted) return;
      setState(() {
        _notifications
          ..clear()
          ..addAll(items.whereType<Map>().map(
                (item) => _TicketNotification.fromJson(
                  Map<String, dynamic>.from(item),
                ),
              ));
        _unreadNotifications = _readInt(data['unread_count']);
      });
    } catch (_) {
      // Non-blocking: ticket list still works without notifications.
    }
  }

  Future<void> _markAllNotificationsRead() async {
    try {
      await ApiClient.send(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/tickets/notifications/read-all',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      await _loadNotifications();
    } catch (_) {}
  }

  void _ticketCreated(TicketEntry ticket) {
    setState(() {
      _tickets.insert(0, ticket);
      _statusFilter = 'All';
      _searchCtrl.clear();
      _tabController.animateTo(0);
    });
    _loadTickets();
  }

  void _openTicketDetails(TicketEntry ticket) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (context) => TicketDetailsPage(
          ticket: ticket,
          onUpdated: (updated) {
            setState(() {
              final index =
                  _tickets.indexWhere((item) => item.id == updated.id);
              if (index >= 0) {
                _tickets[index] = updated;
              }
            });
          },
        ),
      ),
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

    final role = auth.role;
    if (role == 'office' || role == 'admin') {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!context.mounted) return;
        redirectAfterAuth(context, role!, null);
      });
      return const Scaffold(
        backgroundColor: DesignTokens.bgGrey,
        body: Center(
          child: CircularProgressIndicator(color: DesignTokens.maroon),
        ),
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 900;
        final filteredTickets = _tickets
            .where((ticket) => ticket.matches(
                  _searchCtrl.text,
                  _statusFilter,
                ))
            .toList();

        final bodyContent = StudentPage(
          maxWidth: 1120,
          scroll: isWide,
          padding: isWide
              ? const EdgeInsets.fromLTRB(24, 22, 24, 28)
              : const EdgeInsets.fromLTRB(16, 12, 16, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const PublicBackToHomeButton(
                padding: EdgeInsets.only(bottom: 10),
              ),
              HeaderRow(isWide: isWide),
              SizedBox(height: isWide ? 18 : 10),
              TabsRow(tabController: _tabController, filled: !isWide),
              SizedBox(height: isWide ? 18 : 12),
              if (isWide)
                SizedBox(
                  height: 760,
                  child: TabBarView(
                    controller: _tabController,
                    children: [
                      RefreshIndicator(
                        onRefresh: () async {
                          await _loadTickets();
                          await _loadNotifications();
                        },
                        color: DesignTokens.maroon,
                        child: SingleChildScrollView(
                          physics: const AlwaysScrollableScrollPhysics(),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              if (_unreadNotifications > 0) ...[
                                _NotificationsBanner(
                                  notifications: _notifications
                                      .where((item) => !item.isRead)
                                      .take(3)
                                      .toList(),
                                  unreadCount: _unreadNotifications,
                                  onDismiss: _markAllNotificationsRead,
                                ),
                                const SizedBox(height: 16),
                              ],
                              StatsCards(tickets: _tickets),
                              const SizedBox(height: 18),
                              TicketFilters(
                                searchCtrl: _searchCtrl,
                                statusFilter: _statusFilter,
                                onStatusChanged: (value) =>
                                    setState(() => _statusFilter = value),
                                onRefresh: () async {
                                  await _loadTickets();
                                  await _loadNotifications();
                                },
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
                )
              else
                Expanded(
                  child: TabBarView(
                    controller: _tabController,
                    children: [
                      RefreshIndicator(
                        onRefresh: () async {
                          await _loadTickets();
                          await _loadNotifications();
                        },
                        color: DesignTokens.maroon,
                        child: SingleChildScrollView(
                          physics: const AlwaysScrollableScrollPhysics(),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              if (_unreadNotifications > 0) ...[
                                _NotificationsBanner(
                                  notifications: _notifications
                                      .where((item) => !item.isRead)
                                      .take(3)
                                      .toList(),
                                  unreadCount: _unreadNotifications,
                                  onDismiss: _markAllNotificationsRead,
                                ),
                                const SizedBox(height: 12),
                              ],
                              StatsCards(tickets: _tickets, compact: true),
                              const SizedBox(height: 12),
                              TicketFilters(
                                searchCtrl: _searchCtrl,
                                statusFilter: _statusFilter,
                                onStatusChanged: (value) =>
                                    setState(() => _statusFilter = value),
                                onRefresh: () async {
                                  await _loadTickets();
                                  await _loadNotifications();
                                },
                                isRefreshing: _loading,
                              ),
                              const SizedBox(height: 12),
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
                          compact: true,
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        );

        return Scaffold(
          backgroundColor: DesignTokens.bgGrey,
          body: Column(
            children: [
              const PublicSiteHeader(myTicketsActive: true),
              Expanded(child: bodyContent),
            ],
          ),
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
    if (!isWide) {
      return const Padding(
        padding: EdgeInsets.only(bottom: 4),
        child: Text(
          'Tickets',
          style: TextStyle(
            fontSize: 22,
            fontWeight: FontWeight.w900,
            color: DesignTokens.ink,
          ),
        ),
      );
    }
    final isFaculty = AuthScope.of(context).role == 'faculty';
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
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  isFaculty ? 'Faculty Tickets' : 'Student Tickets',
                  style: const TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.w900,
                    color: DesignTokens.ink,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  isFaculty
                      ? 'Create faculty support requests, track progress, and read office replies in one place.'
                      : 'Create support requests, track progress, and read office replies in one place.',
                  style: const TextStyle(fontSize: 14, color: DesignTokens.muted),
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
              child: Text(
                isFaculty ? 'Faculty support' : 'Support Center',
                style: const TextStyle(
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

    return Scaffold(
      backgroundColor: DesignTokens.bgGrey,
      body: Column(
        children: [
          const PublicSiteHeader(myTicketsActive: true),
          Expanded(child: content),
        ],
      ),
    );
  }
}

class TabsRow extends StatelessWidget {
  final TabController tabController;
  final bool filled;
  const TabsRow({required this.tabController, this.filled = false});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: tabController,
      builder: (context, _) {
        return Container(
          padding: const EdgeInsets.all(4),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: DesignTokens.border),
          ),
          child: Row(
            children: [
              Expanded(
                child: _TicketSegmentTab(
                  selected: tabController.index == 0,
                  icon: Icons.fact_check_rounded,
                  label: filled ? 'My tickets' : 'My Tickets',
                  filled: filled,
                  onTap: () => tabController.animateTo(0),
                ),
              ),
              const SizedBox(width: 4),
              Expanded(
                child: _TicketSegmentTab(
                  selected: tabController.index == 1,
                  icon: Icons.add_task_rounded,
                  label: filled ? 'New request' : 'Submit Ticket',
                  filled: filled,
                  onTap: () => tabController.animateTo(1),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _TicketSegmentTab extends StatelessWidget {
  final bool selected;
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool filled;

  const _TicketSegmentTab({
    required this.selected,
    required this.icon,
    required this.label,
    required this.onTap,
    this.filled = false,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected
          ? (filled
              ? DesignTokens.maroon
              : DesignTokens.maroon.withValues(alpha: 0.08))
          : Colors.transparent,
      borderRadius: BorderRadius.circular(10),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          constraints: const BoxConstraints(minHeight: 48),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            border: Border(
              bottom: BorderSide(
                color: selected && !filled
                    ? DesignTokens.maroon
                    : Colors.transparent,
                width: 2.5,
              ),
            ),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                icon,
                size: 18,
                color: selected
                    ? (filled ? Colors.white : DesignTokens.maroon)
                    : DesignTokens.muted,
              ),
              const SizedBox(width: 8),
              Flexible(
                child: Text(
                  label,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
                    color: selected
                        ? (filled ? Colors.white : DesignTokens.maroon)
                        : DesignTokens.muted,
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

class StatsCards extends StatelessWidget {
  final List<TicketEntry> tickets;
  final bool compact;
  const StatsCards({super.key, required this.tickets, this.compact = false});

  @override
  Widget build(BuildContext context) {
    final openCount = tickets.where((t) => t.status == 'Open').length;
    final progressCount =
        tickets.where((t) => t.status == 'In Progress').length;
    final closedCount = tickets.where((t) => t.status == 'Closed').length;
    final totalCount = tickets.length;

    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = compact
            ? 4
            : constraints.maxWidth >= 860
                ? 4
                : constraints.maxWidth >= 560
                    ? 2
                    : 1;
        return StudentResponsiveWrap(
          columns: columns,
          spacing: compact ? 6 : 14,
          children: [
            StatCard(
              number: '$openCount',
              label: compact ? 'Open' : 'Open',
              accent: const Color(0xFF2563EB),
              icon: Icons.mark_email_unread_outlined,
              compact: compact,
            ),
            StatCard(
              number: '$progressCount',
              label: compact ? 'Progress' : 'In Progress',
              accent: const Color(0xFFF97316),
              icon: Icons.sync_rounded,
              compact: compact,
            ),
            StatCard(
              number: '$closedCount',
              label: 'Closed',
              accent: const Color(0xFF16A34A),
              icon: Icons.check_circle_outline_rounded,
              compact: compact,
            ),
            StatCard(
              number: '$totalCount',
              label: 'Total',
              accent: DesignTokens.maroon,
              icon: Icons.confirmation_num_outlined,
              compact: compact,
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

  final bool compact;

  const StatCard({
    super.key,
    required this.number,
    required this.label,
    required this.accent,
    required this.icon,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    if (compact) {
      return Container(
        height: 64,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: DesignTokens.border),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              number,
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w900,
                color: accent,
                height: 1,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              label,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 10,
                color: DesignTokens.muted,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      );
    }
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
  final ValueChanged<String> onStatusChanged;
  final Future<void> Function() onRefresh;
  final bool isRefreshing;

  const TicketFilters({
    super.key,
    required this.searchCtrl,
    required this.statusFilter,
    required this.onStatusChanged,
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
          final statusDropdown = SizedBox(
            width: isNarrow ? null : 200,
            child: _FilterDropdown(
              label: 'Status',
              value: statusFilter,
              values: _statusOptions,
              onChanged: onStatusChanged,
            ),
          );
          final refreshButton = Tooltip(
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
          );

          if (isNarrow) {
            return Column(
              children: [
                searchField,
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(child: statusDropdown),
                    const SizedBox(width: 12),
                    refreshButton,
                  ],
                ),
              ],
            );
          }

          return Row(
            children: [
              Expanded(child: searchField),
              const SizedBox(width: 12),
              statusDropdown,
              const SizedBox(width: 12),
              refreshButton,
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
        icon: Icons.tune_rounded,
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

class TicketDetailsPage extends StatefulWidget {
  final TicketEntry ticket;
  final ValueChanged<TicketEntry>? onUpdated;

  const TicketDetailsPage({
    super.key,
    required this.ticket,
    this.onUpdated,
  });

  @override
  State<TicketDetailsPage> createState() => _TicketDetailsPageState();
}

class _TicketDetailsPageState extends State<TicketDetailsPage> {
  late TicketEntry _ticket;
  final TextEditingController _replyController = TextEditingController();
  final ScrollController _conversationScroll = ScrollController();
  bool _sending = false;
  bool _attaching = false;
  bool _refreshing = false;
  bool _phoneThreadOpen = false;
  String? _replyError;
  Timer? _pollTimer;

  @override
  void initState() {
    super.initState();
    _ticket = widget.ticket;
    _pollTimer = Timer.periodic(const Duration(seconds: 4), (_) {
      if (mounted) _refreshTicket(silent: true);
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _refreshTicket(silent: true);
    });
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _replyController.dispose();
    _conversationScroll.dispose();
    super.dispose();
  }

  bool get _canStudentReply {
    final status = _ticket.status;
    return status == 'Open' ||
        status == 'In Progress' ||
        status == 'Resolved';
  }

  Future<void> _refreshTicket({bool silent = false}) async {
    if (_refreshing) return;
    _refreshing = true;
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/${_ticket.id}',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      final data = _decodeObject(result.body);
      if (result.statusCode < 200 || result.statusCode >= 300 || !mounted) {
        return;
      }
      final updated = TicketEntry.fromJson(data);
      final changed = updated.messages.length != _ticket.messages.length ||
          updated.attachments.length != _ticket.attachments.length ||
          updated.status != _ticket.status ||
          updated.updatedAt != _ticket.updatedAt;
      if (!changed) return;
      setState(() => _ticket = updated);
      widget.onUpdated?.call(updated);
      if (_conversationScroll.hasClients) {
        await Future<void>.delayed(const Duration(milliseconds: 50));
        if (_conversationScroll.hasClients) {
          _conversationScroll.animateTo(
            _conversationScroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 250),
            curve: Curves.easeOut,
          );
        }
      }
    } catch (_) {
      if (!silent && mounted) {
        // Keep current ticket visible; live refresh failures are non-blocking.
      }
    } finally {
      _refreshing = false;
    }
  }

  Future<void> _sendReply() async {
    final message = _replyController.text.trim();
    if (message.isEmpty || _sending || !_canStudentReply) return;
    setState(() {
      _sending = true;
      _replyError = null;
    });
    try {
      final result = await ApiClient.send(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/tickets/${_ticket.id}/replies',
        headers: {...AuthScope.of(context).ticketHeaders()},
        jsonBody: {'message': message},
      );
      final data = _decodeObject(result.body);
      final statusCode = result.statusCode;
      if (statusCode < 200 || statusCode >= 300) {
        throw StateError(_extractError(data, 'Could not send your reply.'));
      }
      final updated = TicketEntry.fromJson(data);
      setState(() {
        _ticket = updated;
        _replyController.clear();
      });
      widget.onUpdated?.call(updated);
    } catch (error) {
      if (!mounted) return;
      setState(() => _replyError = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _pickAndUploadAttachment({required bool imagesOnly}) async {
    if (!_canStudentReply || _attaching || _sending) return;
    try {
      final picked = await pickAppFile(
        allowedExtensions: imagesOnly
            ? const ['png', 'jpg', 'jpeg', 'gif', 'webp']
            : const ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'],
        dialogTitle:
            imagesOnly ? 'Attach image' : 'Attach file (PDF or image)',
      );
      if (picked == null || !mounted) return;
      if (picked.bytes.length > 10 * 1024 * 1024) {
        setState(() => _replyError = 'Attachment must be 10 MB or smaller.');
        return;
      }
      setState(() {
        _attaching = true;
        _replyError = null;
      });
      final headers = AuthScope.of(context).ticketHeaders();
      final result = await ApiClient.multipart(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/tickets/${_ticket.id}/attachments',
        headers: headers,
        files: [
          http.MultipartFile.fromBytes(
            'file',
            picked.bytes,
            filename: picked.name,
          ),
        ],
      );
      if (result.statusCode < 200 || result.statusCode >= 300) {
        final data = _decodeObject(result.body);
        throw StateError(_extractError(data, 'Attachment upload failed.'));
      }
      final refresh = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/${_ticket.id}',
        headers: headers,
      );
      final data = _decodeObject(refresh.body);
      if (refresh.statusCode >= 200 &&
          refresh.statusCode < 300 &&
          mounted) {
        final updated = TicketEntry.fromJson(data);
        setState(() => _ticket = updated);
        widget.onUpdated?.call(updated);
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text('Attached ${picked.name}'),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      setState(() => _replyError = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _attaching = false);
    }
  }

  Future<void> _downloadAttachment(_TicketAttachment file) async {
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}${file.downloadUrl}',
        headers: AuthScope.of(context).ticketHeaders(),
        asBytes: true,
      );
      if (!result.ok) {
        throw StateError('Could not download file.');
      }
      await downloadBytesFile(
        filename: file.originalFilename,
        bytes: result.bytes,
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          backgroundColor: const Color(0xFF991B1B),
          content: Text(_friendlyError(error)),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final ticket = _ticket;
    final officeReplies = ticket.messages
        .where((message) => message.senderRole.toLowerCase() != 'student')
        .length;
    final isWide = MediaQuery.sizeOf(context).width >= 960;
    final phone = MediaQuery.sizeOf(context).width < kPhoneLayoutBreakpoint;

    final detailsPanel = _TicketDetailsSidePanel(ticket: ticket);
    final conversation = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (!(phone && _phoneThreadOpen))
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
            child: Row(
              children: [
                Text(
                  'Conversation',
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontWeight: FontWeight.w800,
                    fontSize: 15,
                  ),
                ),
                const Spacer(),
                Text(
                  '$officeReplies office ${officeReplies == 1 ? 'reply' : 'replies'}',
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                IconButton(
                  tooltip: 'Refresh',
                  onPressed: () => _refreshTicket(),
                  icon: const Icon(Icons.refresh_rounded, size: 20),
                ),
              ],
            ),
          ),
        if (!(phone && _phoneThreadOpen)) const Divider(height: 1),
        Expanded(
          child: ConversationTimeline(
            ticket: ticket,
            scrollController: _conversationScroll,
            onDownloadAttachment: _downloadAttachment,
          ),
        ),
        if (_canStudentReply)
          _TicketReplyComposer(
            controller: _replyController,
            sending: _sending,
            attaching: _attaching,
            error: _replyError,
            onSend: _sendReply,
            onAttachImage: () => _pickAndUploadAttachment(imagesOnly: true),
            onAttachFile: () => _pickAndUploadAttachment(imagesOnly: false),
          )
        else
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(20, 14, 20, 16),
            decoration: const BoxDecoration(
              color: Color(0xFFF8FAFC),
              border: Border(top: BorderSide(color: DesignTokens.border)),
            ),
            child: Text(
              ticket.status == 'Closed'
                  ? 'This ticket is closed. Open a new request if you still need help.'
                  : 'Replies are unavailable for this ticket status.',
              style: const TextStyle(color: DesignTokens.muted, height: 1.4),
            ),
          ),
      ],
    );

    final body = Padding(
      padding: EdgeInsets.fromLTRB(
        phone ? 12 : 20,
        phone ? 8 : 16,
        phone ? 12 : 20,
        phone ? 8 : 20,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              TextButton.icon(
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.arrow_back_rounded, size: 18),
                label: Text(phone ? 'Back' : 'Back to My Tickets'),
              ),
              const Spacer(),
              TicketStatusChip(status: ticket.status),
              const SizedBox(width: 8),
              TicketPriorityChip(priority: ticket.priority),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            ticket.id,
            style: const TextStyle(
              color: DesignTokens.maroon,
              fontWeight: FontWeight.w800,
              fontSize: 12,
              letterSpacing: 0.2,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            ticket.subject,
            maxLines: phone ? 2 : 4,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w800,
              fontSize: phone ? 17 : 24,
              height: 1.25,
            ),
          ),
          SizedBox(height: phone ? 8 : 16),
          Expanded(
            child: isWide
                ? Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(
                        flex: 7,
                        child: StudentPanel(
                          shadow: false,
                          padding: EdgeInsets.zero,
                          child: conversation,
                        ),
                      ),
                      const SizedBox(width: 16),
                      SizedBox(
                        width: 320,
                        child: detailsPanel,
                      ),
                    ],
                  )
                : Column(
                    children: [
                      Theme(
                        data: Theme.of(context).copyWith(
                          dividerColor: Colors.transparent,
                        ),
                        child: StudentPanel(
                          shadow: false,
                          padding: EdgeInsets.zero,
                          child: ExpansionTile(
                            initiallyExpanded: false,
                            tilePadding: const EdgeInsets.symmetric(
                              horizontal: 12,
                              vertical: 0,
                            ),
                            childrenPadding: const EdgeInsets.fromLTRB(
                              12,
                              0,
                              12,
                              12,
                            ),
                            title: const Text(
                              'Ticket details',
                              style: TextStyle(
                                fontWeight: FontWeight.w800,
                                fontSize: 14,
                                color: DesignTokens.ink,
                              ),
                            ),
                            subtitle: Text(
                              '${ticket.category} · ${ticket.assignedOffice}',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                color: DesignTokens.muted,
                                fontSize: 12,
                              ),
                            ),
                            children: [
                              _TicketDetailsSidePanel(
                                ticket: ticket,
                                embed: true,
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 10),
                      Expanded(
                        child: _PhoneConversationLaunchCard(
                          ticket: ticket,
                          officeReplies: officeReplies,
                          onOpen: () =>
                              setState(() => _phoneThreadOpen = true),
                        ),
                      ),
                    ],
                  ),
          ),
        ],
      ),
    );

    if (phone && _phoneThreadOpen) {
      return Scaffold(
        backgroundColor: DesignTokens.bgGrey,
        resizeToAvoidBottomInset: false,
        body: Column(
          children: [
            SafeArea(
              bottom: false,
              child: Material(
                color: Colors.white,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(4, 4, 12, 8),
                  child: Row(
                    children: [
                      IconButton(
                        tooltip: 'Back to ticket',
                        onPressed: () =>
                            setState(() => _phoneThreadOpen = false),
                        icon: const Icon(Icons.arrow_back_rounded),
                      ),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Conversation',
                              style: TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w700,
                                color: DesignTokens.muted,
                              ),
                            ),
                            Text(
                              ticket.subject,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontWeight: FontWeight.w800,
                                fontSize: 15,
                                color: DesignTokens.ink,
                              ),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        tooltip: 'Refresh',
                        onPressed: () => _refreshTicket(),
                        icon: const Icon(Icons.refresh_rounded, size: 20),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            Expanded(child: ColoredBox(color: Colors.white, child: conversation)),
          ],
        ),
      );
    }

    return Scaffold(
      backgroundColor: DesignTokens.bgGrey,
      resizeToAvoidBottomInset: false,
      body: Column(
        children: [
          if (!(phone && phoneKeyboardInset(context) > 48))
            const PublicSiteHeader(myTicketsActive: true),
          Expanded(child: body),
        ],
      ),
    );
  }
}

class _PhoneConversationLaunchCard extends StatelessWidget {
  final TicketEntry ticket;
  final int officeReplies;
  final VoidCallback onOpen;

  const _PhoneConversationLaunchCard({
    required this.ticket,
    required this.officeReplies,
    required this.onOpen,
  });

  String get _preview {
    if (ticket.messages.isNotEmpty) {
      return ticket.messages.last.message.trim();
    }
    return ticket.description.trim();
  }

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      shadow: false,
      padding: EdgeInsets.zero,
      child: Material(
        color: Colors.white,
        child: InkWell(
          onTap: onOpen,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 12, 16),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Conversation',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          fontSize: 15,
                          color: DesignTokens.ink,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        officeReplies == 0
                            ? 'No office replies yet · Tap to open'
                            : '$officeReplies office ${officeReplies == 1 ? 'reply' : 'replies'} · Tap to open',
                        style: const TextStyle(
                          color: DesignTokens.muted,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      if (_preview.isNotEmpty) ...[
                        const SizedBox(height: 10),
                        Text(
                          _preview,
                          maxLines: 4,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: DesignTokens.ink,
                            height: 1.4,
                            fontSize: 13,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const Icon(
                  Icons.chevron_right_rounded,
                  color: DesignTokens.maroon,
                  size: 28,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _TicketDetailsSidePanel extends StatelessWidget {
  final TicketEntry ticket;
  final bool embed;

  const _TicketDetailsSidePanel({
    required this.ticket,
    this.embed = false,
  });

  @override
  Widget build(BuildContext context) {
    final content = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!embed) ...[
              const Text(
                'Ticket details',
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 14,
                  color: DesignTokens.ink,
                ),
              ),
              const SizedBox(height: 12),
            ],
            _DetailGrid(ticket: ticket),
            const SizedBox(height: 16),
            const Text(
              'Description',
              style: TextStyle(
                fontWeight: FontWeight.w800,
                fontSize: 13,
                color: DesignTokens.ink,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              ticket.description.trim().isEmpty
                  ? 'No additional description provided.'
                  : ticket.description,
              style: const TextStyle(
                color: DesignTokens.ink,
                height: 1.45,
                fontSize: 13,
              ),
            ),
            if (ticket.attachments.isNotEmpty) ...[
              const SizedBox(height: 16),
              const Text(
                'Attachments',
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 13,
                  color: DesignTokens.ink,
                ),
              ),
              const SizedBox(height: 8),
              ...ticket.attachments.map(
                (file) => Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: InkWell(
                    onTap: () async {
                      try {
                        final result = await ApiClient.send(
                          method: 'GET',
                          url:
                              '${AppConfig.resolvedApiBase}${file.downloadUrl}',
                          headers: AuthScope.of(context).ticketHeaders(),
                          asBytes: true,
                        );
                        if (!result.ok) {
                          throw StateError('Could not download file.');
                        }
                        await downloadBytesFile(
                          filename: file.originalFilename,
                          bytes: result.bytes,
                        );
                      } catch (error) {
                        if (!context.mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            behavior: SnackBarBehavior.floating,
                            backgroundColor: const Color(0xFF991B1B),
                            content: Text(_friendlyError(error)),
                          ),
                        );
                      }
                    },
                    child: Row(
                      children: [
                        const Icon(Icons.attach_file_rounded,
                            size: 18, color: DesignTokens.maroon),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            file.originalFilename,
                            style: const TextStyle(
                              color: DesignTokens.maroon,
                              fontWeight: FontWeight.w700,
                              fontSize: 12,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ],
        );

    if (embed) return content;
    return StudentPanel(
      shadow: false,
      padding: const EdgeInsets.all(16),
      child: SingleChildScrollView(child: content),
    );
  }
}

class _TicketReplyComposer extends StatelessWidget {
  final TextEditingController controller;
  final bool sending;
  final bool attaching;
  final String? error;
  final VoidCallback onSend;
  final VoidCallback onAttachImage;
  final VoidCallback onAttachFile;

  const _TicketReplyComposer({
    required this.controller,
    required this.sending,
    required this.attaching,
    required this.error,
    required this.onSend,
    required this.onAttachImage,
    required this.onAttachFile,
  });

  @override
  Widget build(BuildContext context) {
    final busy = sending || attaching;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: DesignTokens.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: controller,
            minLines: MediaQuery.sizeOf(context).width < kPhoneLayoutBreakpoint
                ? 1
                : 2,
            maxLines: MediaQuery.sizeOf(context).width < kPhoneLayoutBreakpoint
                ? 3
                : 4,
            enabled: !busy,
            textInputAction: TextInputAction.newline,
            decoration: InputDecoration(
              hintText: 'Write a reply to the office…',
              filled: true,
              fillColor: const Color(0xFFF8FAFC),
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
                borderSide: BorderSide(
                  color: DesignTokens.ink.withValues(alpha: 0.35),
                ),
              ),
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 14,
                vertical: 12,
              ),
            ),
          ),
          if (error != null) ...[
            const SizedBox(height: 8),
            Text(
              error!,
              style: const TextStyle(
                color: Color(0xFFB91C1C),
                fontWeight: FontWeight.w700,
                fontSize: 12,
              ),
            ),
          ],
          if (attaching) ...[
            const SizedBox(height: 8),
            const Text(
              'Uploading attachment…',
              style: TextStyle(
                color: DesignTokens.muted,
                fontWeight: FontWeight.w700,
                fontSize: 12,
              ),
            ),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              IconButton(
                tooltip: 'Attach image',
                onPressed: busy ? null : onAttachImage,
                icon: const Icon(Icons.image),
                color: DesignTokens.maroon,
              ),
              IconButton(
                tooltip: 'Attach PDF or image',
                onPressed: busy ? null : onAttachFile,
                icon: const Icon(Icons.attach_file),
                color: DesignTokens.maroon,
              ),
              const Spacer(),
              ElevatedButton.icon(
                onPressed: busy ? null : onSend,
                icon: sending
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(Icons.send_rounded, size: 18),
                label: Text(sending ? 'Sending…' : 'Send reply'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: DesignTokens.maroon,
                  foregroundColor: Colors.white,
                  elevation: 0,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 18,
                    vertical: 12,
                  ),
                ),
              ),
            ],
          ),
        ],
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
  final ScrollController? scrollController;
  final Future<void> Function(_TicketAttachment file)? onDownloadAttachment;

  const ConversationTimeline({
    super.key,
    required this.ticket,
    this.scrollController,
    this.onDownloadAttachment,
  });

  @override
  Widget build(BuildContext context) {
    final replies = ticket.messages;
    final children = <Widget>[
      StudentConcernBubble(ticket: ticket),
      const SizedBox(height: 14),
      if (replies.isEmpty)
        const _NoOfficeRepliesState()
      else
        ...replies.map(
          (message) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: message.senderRole.toLowerCase() == 'student'
                ? _StudentReplyBubble(message: message)
                : OfficeReplyBubble(message: message),
          ),
        ),
      if (ticket.attachments.isNotEmpty) ...[
        const SizedBox(height: 8),
        const Text(
          'Attachments',
          style: TextStyle(
            fontWeight: FontWeight.w800,
            fontSize: 13,
            color: DesignTokens.ink,
          ),
        ),
        const SizedBox(height: 8),
        ...ticket.attachments.map(
          (file) => Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Material(
              color: const Color(0xFFF8FAFC),
              borderRadius: BorderRadius.circular(10),
              child: InkWell(
                onTap: onDownloadAttachment == null
                    ? null
                    : () => onDownloadAttachment!(file),
                borderRadius: BorderRadius.circular(10),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 10,
                  ),
                  child: Row(
                    children: [
                      Icon(
                        file.isImage
                            ? Icons.image
                            : Icons.picture_as_pdf,
                        size: 18,
                        color: DesignTokens.maroon,
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          file.originalFilename,
                          style: const TextStyle(
                            color: DesignTokens.maroon,
                            fontWeight: FontWeight.w700,
                            fontSize: 12,
                          ),
                        ),
                      ),
                      const Text(
                        'Download',
                        style: TextStyle(
                          color: DesignTokens.maroon,
                          fontWeight: FontWeight.w800,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    ];

    if (scrollController != null) {
      return ListView(
        controller: scrollController,
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 18),
        children: children,
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: children,
    );
  }
}

class _StudentReplyBubble extends StatelessWidget {
  final TicketMessage message;

  const _StudentReplyBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 520),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: const Color(0xFFEFF6FF),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: const Color(0xFFBFDBFE)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'You · ${_formatDate(message.createdAt)}',
              style: const TextStyle(
                color: Color(0xFF1D4ED8),
                fontWeight: FontWeight.w800,
                fontSize: 12,
              ),
            ),
            const SizedBox(height: 6),
            _TicketFormattedText(message.message),
          ],
        ),
      ),
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
            _TicketFormattedText(message.message),
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
            _TicketFormattedText(message.message),
          ],
        ),
      ),
    );
  }
}

class _TicketFormattedText extends StatelessWidget {
  final String text;

  const _TicketFormattedText(this.text);

  @override
  Widget build(BuildContext context) {
    return Text.rich(
      TextSpan(
        style: const TextStyle(color: DesignTokens.ink, height: 1.45),
        children: _parseTicketFormattedSpans(text),
      ),
    );
  }
}

List<InlineSpan> _parseTicketFormattedSpans(String input) {
  if (input.isEmpty) return const [TextSpan(text: '')];
  final pattern = RegExp(
    r'\*\*(.+?)\*\*|_(.+?)_|<u>(.+?)</u>',
    dotAll: true,
  );
  final spans = <InlineSpan>[];
  var start = 0;
  for (final match in pattern.allMatches(input)) {
    if (match.start > start) {
      spans.add(TextSpan(text: input.substring(start, match.start)));
    }
    if (match.group(1) != null) {
      spans.add(TextSpan(
        text: match.group(1),
        style: const TextStyle(fontWeight: FontWeight.w800),
      ));
    } else if (match.group(2) != null) {
      spans.add(TextSpan(
        text: match.group(2),
        style: const TextStyle(fontStyle: FontStyle.italic),
      ));
    } else if (match.group(3) != null) {
      spans.add(TextSpan(
        text: match.group(3),
        style: const TextStyle(decoration: TextDecoration.underline),
      ));
    }
    start = match.end;
  }
  if (start < input.length) {
    spans.add(TextSpan(text: input.substring(start)));
  }
  return spans;
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
  final bool compact;

  const CreateTicketForm({
    super.key,
    this.initialQuestion,
    required this.onCreated,
    this.compact = false,
  });

  @override
  State<CreateTicketForm> createState() => _CreateTicketFormState();
}

class _CreateTicketFormState extends State<CreateTicketForm> {
  final _formKey = GlobalKey<FormState>();
  final TextEditingController _subjectCtrl = TextEditingController();
  final TextEditingController _descCtrl = TextEditingController();
  bool _submitting = false;
  PickedAppFile? _attachmentFile;
  String? _attachmentName;

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

  Future<void> _pickAttachment() async {
    final picked = await pickAppFile(
      allowedExtensions: const [
        'pdf',
        'png',
        'jpg',
        'jpeg',
        'webp',
        'gif',
        'bmp',
        'heic',
        'tif',
        'tiff',
      ],
      dialogTitle: 'Select an attachment',
    );
    if (picked == null) return;
    if (picked.bytes.length > 10 * 1024 * 1024) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          behavior: SnackBarBehavior.floating,
          backgroundColor: Color(0xFF991B1B),
          content: Text('Attachment must be 10 MB or smaller.'),
        ),
      );
      return;
    }
    setState(() {
      _attachmentFile = picked;
      _attachmentName = picked.name;
    });
  }

  Future<void> _uploadAttachment(String ticketId) async {
    final file = _attachmentFile;
    if (file == null) return;
    final result = await ApiClient.multipart(
      method: 'POST',
      url: '${AppConfig.resolvedApiBase}/tickets/$ticketId/attachments',
      headers: AuthScope.of(context).ticketHeaders(),
      files: [
        http.MultipartFile.fromBytes(
          'file',
          file.bytes,
          filename: file.name,
        ),
      ],
    );
    final statusCode = result.statusCode;
    if (statusCode < 200 || statusCode >= 300) {
      final data = _decodeObject(result.body);
      throw StateError(_extractError(data, 'Attachment upload failed.'));
    }
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() => _submitting = true);
    try {
      final body = <String, dynamic>{
        'original_question': _subjectCtrl.text.trim(),
        'description': _descCtrl.text.trim(),
        'source_from_chatbot': widget.initialQuestion != null,
      };
      final result = await ApiClient.send(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/tickets',
        headers: {...AuthScope.of(context).ticketHeaders()},
        jsonBody: body,
      );
      final data = _decodeObject(result.body);
      final statusCode = result.statusCode;
      if (statusCode < 200 || statusCode >= 300) {
        throw StateError(_extractError(data, 'Ticket submission failed.'));
      }
      var ticket = TicketEntry.fromJson(data);
      if (_attachmentFile != null) {
        await _uploadAttachment(ticket.id);
        final refresh = await ApiClient.send(
          method: 'GET',
          url: '${AppConfig.resolvedApiBase}/tickets/${ticket.id}',
          headers: AuthScope.of(context).ticketHeaders(),
        );
        final refreshed = _decodeObject(refresh.body);
        if (refresh.statusCode >= 200 && refresh.statusCode < 300) {
          ticket = TicketEntry.fromJson(refreshed);
        }
      }
      widget.onCreated(ticket);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text('Ticket submitted successfully.'),
        ),
      );
      setState(() {
        _subjectCtrl.clear();
        _descCtrl.clear();
        _attachmentFile = null;
        _attachmentName = null;
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
      padding: widget.compact
          ? const EdgeInsets.fromLTRB(16, 16, 16, 16)
          : const EdgeInsets.fromLTRB(24, 24, 24, 22),
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!widget.compact) ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: const [
                StudentIconBox(
                  icon: Icons.support_agent_rounded,
                  color: DesignTokens.maroon,
                  size: 46,
                ),
                SizedBox(width: 14),
                Expanded(
                  child: StudentSectionTitle(
                    title: 'Submit a Support Request',
                    subtitle:
                        'Share your concern and any details the office will need to help you.',
                  ),
                ),
              ],
            ),
            const SizedBox(height: 24),
            ],
            _FieldLabel(
              label: 'Subject',
              helper: widget.compact
                  ? ''
                  : 'A short summary of what you need help with.',
            ),
            const SizedBox(height: 8),
            TextFormField(
              controller: _subjectCtrl,
              validator: _validateTicketSubject,
              textInputAction: TextInputAction.next,
              decoration: _inputDecoration(
                hintText:
                    'Example: How can I request my transcript of records?',
                icon: Icons.subject_outlined,
              ),
            ),
            const SizedBox(height: 20),
            _FieldLabel(
              label: widget.compact ? 'What happened' : 'Description',
              helper: widget.compact
                  ? 'Dates, office visited, what you already tried.'
                  : 'Include dates, reference numbers, offices visited, or steps you already tried.',
            ),
            const SizedBox(height: 8),
            TextFormField(
              controller: _descCtrl,
              validator: _validateTicketDescription,
              minLines: widget.compact ? 4 : 8,
              maxLines: widget.compact ? 8 : 14,
              decoration: _inputDecoration(
                hintText: 'Tell us what happened and what help you need.',
                icon: Icons.description_outlined,
                alignIconTop: true,
              ),
            ),
            const SizedBox(height: 20),
            _FieldLabel(
              label: widget.compact ? 'File (optional)' : 'Attachment (optional)',
              helper: widget.compact
                  ? 'JPG, PNG, PDF — max 10 MB'
                  : 'Screenshot or document (JPG, PNG, WebP, GIF, PDF — max 10 MB).',
            ),
            const SizedBox(height: 8),
            _AttachmentPicker(
              fileName: _attachmentName,
              onPick: _submitting ? null : _pickAttachment,
              onClear: _submitting || _attachmentName == null
                  ? null
                  : () => setState(() {
                        _attachmentFile = null;
                        _attachmentName = null;
                      }),
            ),
            const SizedBox(height: 24),
            LayoutBuilder(
              builder: (context, constraints) {
                final isNarrow = constraints.maxWidth < 520;
                final clearButton = OutlinedButton.icon(
                  onPressed: _submitting
                      ? null
                      : () {
                          _subjectCtrl.clear();
                          _descCtrl.clear();
                          setState(() {
                            _attachmentFile = null;
                            _attachmentName = null;
                          });
                        },
                  icon: const Icon(Icons.clear_rounded),
                  label: const Text('Clear'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: DesignTokens.ink,
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
                  label: Text(_submitting
                      ? 'Submitting...'
                      : widget.compact
                          ? 'Submit'
                          : 'Submit Ticket'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: DesignTokens.maroon,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 22,
                      vertical: 15,
                    ),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                  ),
                );

                if (isNarrow && !widget.compact) {
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
        if (helper.isNotEmpty) ...[
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
      ],
    );
  }
}

class _AttachmentPicker extends StatelessWidget {
  final String? fileName;
  final VoidCallback? onPick;
  final VoidCallback? onClear;

  const _AttachmentPicker({
    required this.fileName,
    required this.onPick,
    required this.onClear,
  });

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
        children: [
          const StudentIconBox(
            icon: Icons.attach_file_rounded,
            color: DesignTokens.maroon,
            size: 38,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              fileName == null || fileName!.isEmpty
                  ? 'No file selected'
                  : fileName!,
              style: TextStyle(
                color: fileName == null ? DesignTokens.muted : DesignTokens.ink,
                height: 1.35,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          if (onClear != null)
            TextButton(
              onPressed: onClear,
              child: const Text('Remove'),
            ),
          TextButton.icon(
            onPressed: onPick,
            icon: const Icon(Icons.upload_file_rounded, size: 18),
            label: Text(fileName == null ? 'Choose file' : 'Change'),
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
      borderSide: BorderSide(
        color: DesignTokens.ink.withValues(alpha: 0.35),
        width: 1.2,
      ),
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

int _readInt(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse('$value') ?? 0;
}

class _TicketAttachment {
  final String id;
  final String ticketId;
  final String originalFilename;
  final String contentType;
  final int sizeBytes;
  final String downloadUrl;

  const _TicketAttachment({
    required this.id,
    required this.ticketId,
    required this.originalFilename,
    required this.contentType,
    required this.sizeBytes,
    required this.downloadUrl,
  });

  factory _TicketAttachment.fromJson(Map<String, dynamic> json) {
    return _TicketAttachment(
      id: (json['id'] ?? '').toString(),
      ticketId: (json['ticket_id'] ?? '').toString(),
      originalFilename: (json['original_filename'] ?? 'file').toString(),
      contentType: (json['content_type'] ?? '').toString(),
      sizeBytes: _readInt(json['size_bytes']),
      downloadUrl: (json['download_url'] ?? '').toString(),
    );
  }

  bool get isImage => contentType.toLowerCase().startsWith('image/');
}

class _TicketNotification {
  final String id;
  final String? ticketId;
  final String type;
  final String title;
  final String body;
  final bool isRead;

  const _TicketNotification({
    required this.id,
    required this.ticketId,
    required this.type,
    required this.title,
    required this.body,
    required this.isRead,
  });

  factory _TicketNotification.fromJson(Map<String, dynamic> json) {
    return _TicketNotification(
      id: (json['id'] ?? '').toString(),
      ticketId: json['ticket_id']?.toString(),
      type: (json['type'] ?? '').toString(),
      title: (json['title'] ?? 'Update').toString(),
      body: (json['body'] ?? '').toString(),
      isRead: json['is_read'] == true,
    );
  }
}

class _NotificationsBanner extends StatelessWidget {
  final List<_TicketNotification> notifications;
  final int unreadCount;
  final VoidCallback onDismiss;

  const _NotificationsBanner({
    required this.notifications,
    required this.unreadCount,
    required this.onDismiss,
  });

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.notifications_active_rounded,
                  color: DesignTokens.maroon),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '$unreadCount new ticket update${unreadCount == 1 ? '' : 's'}',
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    color: DesignTokens.ink,
                  ),
                ),
              ),
              TextButton(
                onPressed: onDismiss,
                child: const Text('Mark all read'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ...notifications.map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.title,
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      color: DesignTokens.ink,
                    ),
                  ),
                  Text(
                    item.body,
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontSize: 13,
                    ),
                  ),
                ],
              ),
            ),
          ),
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

String? _validateTicketSubject(String? value) {
  final cleaned = (value ?? '').trim().replaceAll(RegExp(r'\s+'), ' ');
  if (cleaned.length < 8) {
    return 'Subject must be at least 8 characters.';
  }
  final words = RegExp(r"[A-Za-zÀ-ÿ]{2,}").allMatches(cleaned).toList();
  if (words.length < 2) {
    return 'Use at least two real words in the subject.';
  }
  return _unreadableTicketTextMessage(
    cleaned,
    words.map((m) => m.group(0)!).toList(),
    minLetters: 6,
  );
}

String? _validateTicketDescription(String? value) {
  final cleaned = (value ?? '').trim().replaceAll(RegExp(r'\s+'), ' ');
  if (cleaned.length < 20) {
    return 'Description must be at least 20 characters. Add dates, steps tried, or what you need.';
  }
  final words = RegExp(r"[A-Za-zÀ-ÿ]{2,}").allMatches(cleaned).toList();
  if (words.length < 4) {
    return 'Use at least four real words so the office has enough context.';
  }
  return _unreadableTicketTextMessage(
    cleaned,
    words.map((m) => m.group(0)!).toList(),
    minLetters: 10,
  );
}

String? _unreadableTicketTextMessage(
  String cleaned,
  List<String> words, {
  int minLetters = 10,
}) {
  final letters = cleaned
      .toLowerCase()
      .split('')
      .where((ch) => RegExp(r'[a-zà-ÿ]').hasMatch(ch))
      .toList();
  if (letters.length < minLetters) {
    return 'Please write a clearer message in plain language.';
  }
  const vowels = 'aeiouáéíóúäëïöüàèìòùâêîôû';
  final vowelCount = letters.where((ch) => vowels.contains(ch)).length;
  final vowelRatio = vowelCount / letters.length;
  if (vowelRatio < 0.18 || vowelRatio > 0.72) {
    return 'This does not look like readable text. Please rewrite it in plain language.';
  }
  for (final word in words) {
    if (word.length < 10) continue;
    final wordLetters = word.toLowerCase().split('');
    final wordVowels =
        wordLetters.where((ch) => vowels.contains(ch)).length;
    if (wordVowels / wordLetters.length < 0.2) {
      return 'This contains unreadable text. Please rewrite it in plain language.';
    }
  }
  if (RegExp(r'[bcdfghjklmnpqrstvwxyz]{6,}', caseSensitive: false)
      .hasMatch(cleaned)) {
    return 'This contains unreadable text. Please rewrite it in plain language.';
  }
  final lowered = cleaned.toLowerCase();
  for (final ch in lowered.split('').toSet()) {
    if (RegExp(r'[a-zà-ÿ]').hasMatch(ch) && lowered.contains(ch * 5)) {
      return 'This contains unreadable text. Please rewrite it in plain language.';
    }
  }
  return null;
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
