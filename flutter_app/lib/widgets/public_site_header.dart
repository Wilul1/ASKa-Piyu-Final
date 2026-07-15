import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../screens/chatbot_page.dart';
import '../screens/knowledge_base_page.dart';
import '../screens/login_page.dart';
import '../screens/my_tickets_page.dart';
import '../screens/signup_page.dart';
import '../screens/student_home.dart';

/// Shared top navigation for public landing / Knowledge Base (no sidebar).
class PublicSiteHeader extends StatelessWidget {
  final bool knowledgeBaseActive;
  final bool askAssistantActive;

  const PublicSiteHeader({
    super.key,
    this.knowledgeBaseActive = false,
    this.askAssistantActive = false,
  });

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final isNarrow = width < 880;
    final auth = AuthScope.of(context);
    final isAuthed = auth.isAuthenticated;
    final role = auth.role;

    return Material(
      color: Colors.white,
      child: Container(
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: Color(0xFFEEF1F5))),
        ),
        padding: EdgeInsets.symmetric(
          horizontal: isNarrow ? 16 : 28,
          vertical: 14,
        ),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: Row(
              children: [
                InkWell(
                  onTap: () {
                    Navigator.of(context).pushAndRemoveUntil(
                      MaterialPageRoute(
                          builder: (_) => const StudentHomePage()),
                      (route) => false,
                    );
                  },
                  borderRadius: BorderRadius.circular(8),
                  child: Image.asset(
                    'assets/brandmark.png',
                    height: 36,
                    fit: BoxFit.contain,
                    filterQuality: FilterQuality.high,
                  ),
                ),
                const Spacer(),
                if (!isNarrow) ...[
                  _NavLink(
                    label: 'Knowledge Base',
                    active: knowledgeBaseActive,
                    onTap: () {
                      if (knowledgeBaseActive) return;
                      Navigator.of(context).push(
                        MaterialPageRoute(
                            builder: (_) => const KnowledgeBasePage()),
                      );
                    },
                  ),
                  _NavLink(
                    label: 'Ask Assistant',
                    active: askAssistantActive,
                    onTap: () {
                      if (askAssistantActive) return;
                      Navigator.of(context).push(
                        MaterialPageRoute(builder: (_) => const ChatbotPage()),
                      );
                    },
                  ),
                  _NavLink(
                    label: 'My Tickets',
                    onTap: () => openProtectedPage(
                      context,
                      builder: (_) => const MyTicketsPage(),
                    ),
                  ),
                  if (!isAuthed)
                    _NavLink(
                      label: 'Sign in',
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute(builder: (_) => const LoginPage()),
                      ),
                    )
                  else
                    _NavLink(
                      label: role == 'office'
                          ? 'Office'
                          : role == 'admin'
                              ? 'Admin'
                              : 'Account',
                      onTap: () {
                        if (role == 'office' || role == 'admin') {
                          redirectAfterAuth(context, role ?? 'student', null);
                        } else {
                          openProtectedPage(
                            context,
                            builder: (_) => const MyTicketsPage(),
                          );
                        }
                      },
                    ),
                  const SizedBox(width: 10),
                ],
                if (!isAuthed)
                  ElevatedButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const SignupPage()),
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF5C0A0F),
                      foregroundColor: Colors.white,
                      elevation: 0,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 20, vertical: 14),
                      shape: const StadiumBorder(),
                    ),
                    child: const Text(
                      'Create account',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                  )
                else if (!isNarrow)
                  OutlinedButton(
                    onPressed: () => AuthScope.of(context).logout(),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: DesignTokens.maroon,
                      side: const BorderSide(color: DesignTokens.maroon),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 16, vertical: 14),
                      shape: const StadiumBorder(),
                    ),
                    child: const Text('Sign out'),
                  ),
                if (isNarrow)
                  IconButton(
                    tooltip: 'Menu',
                    onPressed: () => _openMobileMenu(context),
                    icon: const Icon(Icons.menu_rounded,
                        color: DesignTokens.maroon),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _openMobileMenu(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (context) {
        final auth = AuthScope.of(context);
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                title: const Text('Home'),
                onTap: () {
                  Navigator.pop(context);
                  Navigator.of(context).pushAndRemoveUntil(
                    MaterialPageRoute(builder: (_) => const StudentHomePage()),
                    (route) => false,
                  );
                },
              ),
              ListTile(
                title: const Text('Knowledge Base'),
                onTap: () {
                  Navigator.pop(context);
                  if (!knowledgeBaseActive) {
                    Navigator.of(context).push(MaterialPageRoute(
                        builder: (_) => const KnowledgeBasePage()));
                  }
                },
              ),
              ListTile(
                title: const Text('Ask Assistant'),
                onTap: () {
                  Navigator.pop(context);
                  Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const ChatbotPage()));
                },
              ),
              ListTile(
                title: const Text('My Tickets'),
                onTap: () {
                  Navigator.pop(context);
                  openProtectedPage(
                    context,
                    builder: (_) => const MyTicketsPage(),
                  );
                },
              ),
              if (!auth.isAuthenticated) ...[
                ListTile(
                  title: const Text('Sign in'),
                  onTap: () {
                    Navigator.pop(context);
                    Navigator.of(context).push(
                        MaterialPageRoute(builder: (_) => const LoginPage()));
                  },
                ),
                ListTile(
                  title: const Text('Create account'),
                  onTap: () {
                    Navigator.pop(context);
                    Navigator.of(context).push(
                        MaterialPageRoute(builder: (_) => const SignupPage()));
                  },
                ),
              ] else
                ListTile(
                  title: const Text('Sign out'),
                  onTap: () {
                    AuthScope.of(context).logout();
                    Navigator.pop(context);
                  },
                ),
            ],
          ),
        );
      },
    );
  }
}

class _NavLink extends StatelessWidget {
  final String label;
  final VoidCallback onTap;
  final bool active;

  const _NavLink({
    required this.label,
    required this.onTap,
    this.active = false,
  });

  @override
  Widget build(BuildContext context) {
    return TextButton(
      onPressed: onTap,
      style: TextButton.styleFrom(
        foregroundColor:
            active ? DesignTokens.maroon : const Color(0xFF4B5563),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontWeight: active ? FontWeight.w900 : FontWeight.w700,
          fontSize: 14,
        ),
      ),
    );
  }
}
