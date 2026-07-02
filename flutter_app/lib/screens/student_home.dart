import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../widgets/sidebar.dart';
import '../widgets/student_ui.dart';
import 'chatbot_page.dart';
import 'knowledge_base_page.dart';
import 'my_tickets_page.dart';

class StudentHomePage extends StatelessWidget {
  const StudentHomePage({super.key});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 900;
        const content = _DashboardContent();
        if (isWide) {
          return const Scaffold(
            backgroundColor: DesignTokens.bgGrey,
            body: Row(
              children: [
                SizedBox(
                    width: 220,
                    child: AppSidebar(current: StudentNavItem.home)),
                Expanded(child: content),
              ],
            ),
          );
        }

        return Scaffold(
          backgroundColor: DesignTokens.bgGrey,
          drawer: const Drawer(child: AppSidebar(current: StudentNavItem.home)),
          appBar: AppBar(title: const Text('ASKa-Piyu')),
          body: content,
        );
      },
    );
  }
}

class _DashboardContent extends StatelessWidget {
  const _DashboardContent();

  @override
  Widget build(BuildContext context) {
    final isStudent = AuthScope.of(context).role == 'student';

    return StudentPage(
      child: LayoutBuilder(
        builder: (context, constraints) {
          final desktop = constraints.maxWidth >= 980;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _WelcomeHeader(desktop: desktop),
              const SizedBox(height: 20),
              _QuickActions(isStudent: isStudent),
              const SizedBox(height: 22),
              if (desktop)
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Expanded(
                      flex: 7,
                      child: Column(
                        children: [
                          _PopularTopics(),
                          SizedBox(height: 22),
                          _SuggestedArticles(),
                        ],
                      ),
                    ),
                    const SizedBox(width: 22),
                    Expanded(
                      flex: 4,
                      child: Column(
                        children: [
                          if (isStudent) const _TicketSummary(),
                          if (isStudent) const SizedBox(height: 22),
                          const _Announcements(),
                        ],
                      ),
                    ),
                  ],
                )
              else ...[
                const _PopularTopics(),
                const SizedBox(height: 22),
                if (isStudent) const _TicketSummary(),
                if (isStudent) const SizedBox(height: 22),
                const _Announcements(),
                const SizedBox(height: 22),
                const _SuggestedArticles(),
              ],
            ],
          );
        },
      ),
    );
  }
}

class _WelcomeHeader extends StatelessWidget {
  final bool desktop;

  const _WelcomeHeader({required this.desktop});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: EdgeInsets.fromLTRB(24, desktop ? 30 : 24, 24, 24),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Colors.white, Color(0xFFFFFBF0)],
        ),
        border: Border.all(color: const Color(0xFFF1E4C8)),
        boxShadow: DesignTokens.softShadow(0.07),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 18,
            runSpacing: 12,
            children: [
              ConstrainedBox(
                constraints: BoxConstraints(maxWidth: desktop ? 600 : 700),
                child: const Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Welcome back',
                        style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w900,
                            color: DesignTokens.maroon)),
                    SizedBox(height: 8),
                    Text('Your ASKa-Piyu dashboard',
                        style: TextStyle(
                            fontSize: 34,
                            height: 1.12,
                            fontWeight: FontWeight.w900,
                            color: DesignTokens.ink)),
                    SizedBox(height: 10),
                    Text(
                      'Search help articles, ask the assistant, and track support requests from one place.',
                      style: TextStyle(
                          fontSize: 15,
                          height: 1.45,
                          color: DesignTokens.muted),
                    ),
                  ],
                ),
              ),
              _StatusPill(),
            ],
          ),
          const SizedBox(height: 24),
          const _MainSearchBar(),
        ],
      ),
    );
  }
}

class _MainSearchBar extends StatelessWidget {
  const _MainSearchBar();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(6),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0xFFE2E8F0)),
        boxShadow: DesignTokens.softShadow(0.08),
      ),
      child: Row(
        children: [
          const SizedBox(width: 10),
          const Icon(Icons.search_rounded, color: DesignTokens.muted, size: 23),
          const SizedBox(width: 10),
          const Expanded(
            child: TextField(
              decoration: InputDecoration(
                hintText: 'Search articles, services, tickets...',
                border: InputBorder.none,
                isDense: true,
                hintStyle: TextStyle(color: Color(0xFF94A3B8)),
              ),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            height: 46,
            child: ElevatedButton.icon(
              onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const KnowledgeBasePage())),
              icon: const Icon(Icons.arrow_forward_rounded, size: 18),
              label: const Text('Search'),
              style: ElevatedButton.styleFrom(
                backgroundColor: DesignTokens.maroon,
                foregroundColor: Colors.white,
                elevation: 0,
                padding: const EdgeInsets.symmetric(horizontal: 18),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14)),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _QuickActions extends StatelessWidget {
  final bool isStudent;

  const _QuickActions({required this.isStudent});

  @override
  Widget build(BuildContext context) {
    final actions = [
      _ActionData('Ask ASKa-Piyu', 'Start a guided support chat.',
          Icons.smart_toy_rounded, DesignTokens.maroon, () {
        Navigator.of(context)
            .push(MaterialPageRoute(builder: (_) => const ChatbotPage()));
      }),
      _ActionData('Knowledge Base', 'Browse articles and categories.',
          Icons.menu_book_rounded, const Color(0xFF2563EB), () {
        Navigator.of(context)
            .push(MaterialPageRoute(builder: (_) => const KnowledgeBasePage()));
      }),
      if (isStudent)
        _ActionData('Submit Ticket', 'Send a request to the right office.',
            Icons.add_task_rounded, DesignTokens.gold, () {
          openProtectedPage(
            context,
            builder: (_) => const MyTicketsPage(initialTab: 1),
          );
        }),
      if (isStudent)
        _ActionData('My Tickets', 'Check status and updates.',
            Icons.fact_check_rounded, const Color(0xFF16A34A), () {
          openProtectedPage(
            context,
            builder: (_) => const MyTicketsPage(),
          );
        }),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const StudentSectionTitle(
          title: 'Quick Actions',
          subtitle: 'Jump into the support task you need right now.',
        ),
        const SizedBox(height: 12),
        LayoutBuilder(
          builder: (context, constraints) {
            final columns = constraints.maxWidth >= 980
                ? 4
                : constraints.maxWidth >= 620
                    ? 2
                    : 1;
            return StudentResponsiveWrap(
              columns: columns,
              spacing: 14,
              children:
                  actions.map((action) => _ActionCard(data: action)).toList(),
            );
          },
        ),
      ],
    );
  }
}

class _ActionCard extends StatelessWidget {
  final _ActionData data;

  const _ActionCard({required this.data});

  @override
  Widget build(BuildContext context) {
    return StudentInkCard(
      onTap: data.onTap,
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StudentIconBox(icon: data.icon, color: data.color, size: 46),
          const SizedBox(height: 16),
          Text(data.title,
              style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w900,
                  color: DesignTokens.ink)),
          const SizedBox(height: 6),
          Text(data.description,
              style: const TextStyle(
                  fontSize: 13, height: 1.35, color: DesignTokens.muted)),
        ],
      ),
    );
  }
}

class _PopularTopics extends StatelessWidget {
  const _PopularTopics();

  @override
  Widget build(BuildContext context) {
    const topics = [
      'Enrollment',
      'Scholarship',
      'Excuse Slip',
      'TOR',
      'Graduation',
      'Tuition',
      'ID Replacement',
      'Retention Policy',
    ];
    return StudentPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StudentSectionTitle(
              title: 'Popular Topics',
              subtitle: 'Common searches from students this week.'),
          const SizedBox(height: 14),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: topics
                .map((topic) => ActionChip(
                      avatar: const Icon(Icons.article_outlined, size: 16),
                      label: Text(topic),
                      onPressed: () => Navigator.of(context).push(
                          MaterialPageRoute(
                              builder: (_) => const KnowledgeBasePage())),
                      backgroundColor: Colors.white,
                      side: const BorderSide(color: DesignTokens.border),
                      labelStyle: const TextStyle(
                          fontWeight: FontWeight.w800, color: DesignTokens.ink),
                    ))
                .toList(),
          ),
        ],
      ),
    );
  }
}

class _TicketSummary extends StatelessWidget {
  const _TicketSummary();

  @override
  Widget build(BuildContext context) {
    const metrics = [
      _MetricData('Open', '0', Color(0xFF2563EB)),
      _MetricData('In Progress', '0', Color(0xFFF97316)),
      _MetricData('Closed', '0', Color(0xFF16A34A)),
    ];
    return StudentPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StudentSectionTitle(
              title: 'Ticket Summary',
              subtitle: 'A quick view of your current support requests.'),
          const SizedBox(height: 14),
          ...metrics.map((metric) => _MetricRow(data: metric)),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () => openProtectedPage(
                context,
                builder: (_) => const MyTicketsPage(),
              ),
              icon: const Icon(Icons.fact_check_outlined, size: 18),
              label: const Text('View My Tickets'),
              style: OutlinedButton.styleFrom(
                foregroundColor: DesignTokens.maroon,
                side: const BorderSide(color: DesignTokens.maroon),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14)),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Announcements extends StatelessWidget {
  const _Announcements();

  @override
  Widget build(BuildContext context) {
    const updates = [
      'Enrollment help articles were refreshed.',
      'Scholarship requirement guides were reviewed.',
      'New student services forms are now easier to find.',
    ];
    return StudentPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StudentSectionTitle(
              title: 'Announcements',
              subtitle: 'Recent updates from ASKa-Piyu support.'),
          const SizedBox(height: 12),
          ...updates.map((update) => Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const StudentIconBox(
                        icon: Icons.campaign_rounded,
                        color: DesignTokens.gold,
                        size: 38),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(update,
                          style: const TextStyle(
                              fontSize: 13,
                              height: 1.4,
                              fontWeight: FontWeight.w700,
                              color: DesignTokens.ink)),
                    ),
                  ],
                ),
              )),
        ],
      ),
    );
  }
}

class _SuggestedArticles extends StatelessWidget {
  const _SuggestedArticles();

  @override
  Widget build(BuildContext context) {
    const articles = [
      _ArticleData('Enrollment Procedures', 'Admission & Enrollment'),
      _ArticleData('Requirements for TOR', 'Registrar'),
      _ArticleData('How to Get an Excuse Slip', 'OSAS'),
      _ArticleData('Payment of Tuition', 'Finance Office'),
    ];
    return StudentPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StudentSectionTitle(
              title: 'Suggested Articles and Services',
              subtitle: 'Useful starting points for common concerns.'),
          const SizedBox(height: 12),
          ...articles.map((article) => StudentInkCard(
                margin: const EdgeInsets.only(bottom: 10),
                shadow: false,
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => const KnowledgeBasePage())),
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    const StudentIconBox(
                        icon: Icons.description_outlined,
                        color: DesignTokens.maroon,
                        size: 38),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(article.title,
                              style: const TextStyle(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w900,
                                  color: DesignTokens.ink)),
                          const SizedBox(height: 4),
                          Text(article.category,
                              style: const TextStyle(
                                  fontSize: 12, color: DesignTokens.muted)),
                        ],
                      ),
                    ),
                    const Icon(Icons.chevron_right_rounded,
                        color: DesignTokens.muted),
                  ],
                ),
              )),
        ],
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill();

  @override
  Widget build(BuildContext context) {
    final role = AuthScope.of(context).role;
    final label = role == 'admin'
        ? 'Admin workspace'
        : role == 'student'
            ? 'Student support center'
            : role == 'office'
                ? 'Office workspace'
                : 'Public support center';

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: DesignTokens.maroon.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: DesignTokens.maroon.withValues(alpha: 0.12)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.verified_rounded,
              color: DesignTokens.maroon, size: 18),
          const SizedBox(width: 8),
          Text(label,
              style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w900,
                  color: DesignTokens.maroon)),
        ],
      ),
    );
  }
}

class _MetricRow extends StatelessWidget {
  final _MetricData data;

  const _MetricRow({required this.data});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        children: [
          Expanded(
            child: Text(data.label,
                style: const TextStyle(
                    fontWeight: FontWeight.w800, color: DesignTokens.ink)),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: data.color.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(999),
            ),
            child: Text(data.value,
                style:
                    TextStyle(fontWeight: FontWeight.w900, color: data.color)),
          ),
        ],
      ),
    );
  }
}

class _ActionData {
  final String title;
  final String description;
  final IconData icon;
  final Color color;
  final VoidCallback onTap;

  const _ActionData(
      this.title, this.description, this.icon, this.color, this.onTap);
}

class _MetricData {
  final String label;
  final String value;
  final Color color;

  const _MetricData(this.label, this.value, this.color);
}

class _ArticleData {
  final String title;
  final String category;

  const _ArticleData(this.title, this.category);
}
