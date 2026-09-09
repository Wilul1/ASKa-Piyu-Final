import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../navigation/soft_page_route.dart';
import '../screens/chatbot_page.dart';
import '../screens/knowledge_base_page.dart';
import '../screens/login_page.dart';
import '../screens/my_tickets_page.dart';
import '../screens/settings_page.dart';
import '../screens/signup_page.dart';
import '../screens/student_home.dart';

/// Shared top navigation for public landing / Knowledge Base (no sidebar).
class PublicSiteHeader extends StatelessWidget {
  final bool knowledgeBaseActive;
  final bool askAssistantActive;
  final bool myTicketsActive;
  final bool accountActive;
  final bool slim;

  const PublicSiteHeader({
    super.key,
    this.knowledgeBaseActive = false,
    this.askAssistantActive = false,
    this.myTicketsActive = false,
    this.accountActive = false,
    this.slim = false,
  });

  bool get _onPublicPeerPage =>
      knowledgeBaseActive || askAssistantActive || myTicketsActive || accountActive;

  Future<void> _goHome(BuildContext context) =>
      softPushAndClear(context, const StudentHomePage());

  Future<void> _goPeer(BuildContext context, Widget page) {
    if (_onPublicPeerPage) {
      return softReplace(context, page);
    }
    return softPush(context, page);
  }

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
          horizontal: isNarrow ? 12 : 28,
          vertical: slim && isNarrow ? 8 : 14,
        ),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: Row(
              children: [
                InkWell(
                  onTap: () => _goHome(context),
                  borderRadius: BorderRadius.circular(8),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Image.asset(
                        'assets/brandmark.png',
                        height: slim && isNarrow ? 28 : 36,
                        fit: BoxFit.contain,
                        filterQuality: FilterQuality.high,
                      ),
                      const SizedBox(width: 10),
                      Text(
                        slim && isNarrow && askAssistantActive
                            ? 'Ask Assistant'
                            : 'ASKa-Piyu',
                        style: TextStyle(
                          color: DesignTokens.maroon,
                          fontWeight: FontWeight.w900,
                          fontSize: slim && isNarrow ? 15 : 18,
                          letterSpacing: -0.2,
                          height: 1,
                        ),
                      ),
                    ],
                  ),
                ),
                const Spacer(),
                if (!isNarrow) ...[
                  _NavLink(
                    label: 'Knowledge Base',
                    active: knowledgeBaseActive,
                    onTap: () {
                      if (knowledgeBaseActive) return;
                      _goPeer(context, const KnowledgeBasePage());
                    },
                  ),
                  _NavLink(
                    label: 'Ask Assistant',
                    active: askAssistantActive,
                    onTap: () {
                      if (askAssistantActive) return;
                      _goPeer(context, const ChatbotPage());
                    },
                  ),
                  _NavLink(
                    label: 'My Tickets',
                    active: myTicketsActive,
                    onTap: () {
                      if (myTicketsActive) return;
                      openProtectedPage(
                        context,
                        builder: (_) => const MyTicketsPage(),
                        replace: _onPublicPeerPage,
                        requireVerifiedEmail: true,
                        message: emailVerifyRequiredMessage,
                      );
                    },
                  ),
                  if (!isAuthed)
                    _NavLink(
                      label: 'Login',
                      onTap: () => softPush(context, const LoginPage()),
                    )
                  else
                    _NavLink(
                      label: role == 'office'
                          ? 'Office'
                          : role == 'admin'
                              ? 'Admin'
                              : 'Account',
                      active: accountActive &&
                          role != 'office' &&
                          role != 'admin',
                      onTap: () {
                        if (role == 'office' || role == 'admin') {
                          redirectAfterAuth(context, role ?? 'student', null);
                        } else if (accountActive) {
                          return;
                        } else {
                          openProtectedPage(
                            context,
                            builder: (_) => const SettingsPage(),
                            replace: _onPublicPeerPage,
                          );
                        }
                      },
                    ),
                  const SizedBox(width: 10),
                ],
                if (!isAuthed && !isNarrow)
                  ElevatedButton(
                    onPressed: () => softPush(context, const SignupPage()),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF5C0A0F),
                      foregroundColor: Colors.white,
                      elevation: 0,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 20, vertical: 14),
                      shape: const StadiumBorder(),
                    ),
                    child: const Text(
                      'Sign up',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                  )
                else if (!isNarrow && isAuthed)
                  OutlinedButton(
                    onPressed: () => signOutToHome(context),
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
                    style: IconButton.styleFrom(
                      minimumSize: const Size(44, 44),
                      tapTargetSize: MaterialTapTargetSize.padded,
                      side: const BorderSide(color: Color(0xFFE5EAF1)),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    icon: const Icon(Icons.menu_rounded, color: DesignTokens.maroon),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _openMobileMenu(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final drawerWidth = width < 360 ? width * 0.92 : (width * 0.82).clamp(260.0, 320.0);

    showGeneralDialog<void>(
      context: context,
      barrierDismissible: true,
      barrierLabel: 'Close menu',
      barrierColor: Colors.black54,
      transitionDuration: const Duration(milliseconds: 220),
      pageBuilder: (dialogContext, animation, secondaryAnimation) {
        final auth = AuthScope.of(dialogContext);
        Widget item({
          required String label,
          required bool active,
          required VoidCallback onTap,
        }) {
          return Material(
            color: active ? const Color(0xFFFCE8EA) : Colors.transparent,
            borderRadius: BorderRadius.circular(12),
            child: InkWell(
              borderRadius: BorderRadius.circular(12),
              onTap: () {
                Navigator.pop(dialogContext);
                onTap();
              },
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                child: Row(
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        color: active ? DesignTokens.maroon : const Color(0xFFD1D5DB),
                        borderRadius: BorderRadius.circular(2),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        label,
                        style: TextStyle(
                          fontWeight: active ? FontWeight.w800 : FontWeight.w700,
                          color: active ? DesignTokens.maroon : const Color(0xFF374151),
                          fontSize: 15,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }

        return Align(
          alignment: Alignment.centerRight,
          child: Material(
            color: Colors.white,
            child: SizedBox(
              width: drawerWidth,
              height: MediaQuery.sizeOf(dialogContext).height,
              child: SafeArea(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(14, 10, 14, 18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        children: [
                          const Text(
                            'Menu',
                            style: TextStyle(
                              fontWeight: FontWeight.w900,
                              fontSize: 18,
                            ),
                          ),
                          const Spacer(),
                          IconButton(
                            tooltip: 'Close',
                            onPressed: () => Navigator.pop(dialogContext),
                            icon: const Icon(Icons.close_rounded),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Explore',
                        style: TextStyle(
                          fontSize: 11,
                          letterSpacing: 0.8,
                          fontWeight: FontWeight.w800,
                          color: DesignTokens.muted,
                        ),
                      ),
                      const SizedBox(height: 6),
                      item(
                        label: 'Home',
                        active: !_onPublicPeerPage,
                        onTap: () => _goHome(context),
                      ),
                      item(
                        label: 'Knowledge Base',
                        active: knowledgeBaseActive,
                        onTap: () {
                          if (!knowledgeBaseActive) {
                            _goPeer(context, const KnowledgeBasePage());
                          }
                        },
                      ),
                      item(
                        label: 'Ask Assistant',
                        active: askAssistantActive,
                        onTap: () {
                          if (!askAssistantActive) {
                            _goPeer(context, const ChatbotPage());
                          }
                        },
                      ),
                      item(
                        label: 'My Tickets',
                        active: myTicketsActive,
                        onTap: () {
                          openProtectedPage(
                            context,
                            builder: (_) => const MyTicketsPage(),
                            replace: _onPublicPeerPage,
                            requireVerifiedEmail: true,
                            message: emailVerifyRequiredMessage,
                          );
                        },
                      ),
                      const SizedBox(height: 12),
                      Text(
                        'Account',
                        style: TextStyle(
                          fontSize: 11,
                          letterSpacing: 0.8,
                          fontWeight: FontWeight.w800,
                          color: DesignTokens.muted,
                        ),
                      ),
                      const SizedBox(height: 6),
                      if (!auth.isAuthenticated) ...[
                        item(
                          label: 'Log in',
                          active: false,
                          onTap: () => softPush(context, const LoginPage()),
                        ),
                        const Spacer(),
                        ElevatedButton(
                          onPressed: () {
                            Navigator.pop(dialogContext);
                            softPush(context, const SignupPage());
                          },
                          style: ElevatedButton.styleFrom(
                            backgroundColor: DesignTokens.maroon,
                            foregroundColor: Colors.white,
                            elevation: 0,
                            minimumSize: const Size.fromHeight(48),
                            shape: const StadiumBorder(),
                          ),
                          child: const Text(
                            'Sign up',
                            style: TextStyle(fontWeight: FontWeight.w800),
                          ),
                        ),
                      ] else ...[
                        item(
                          label: auth.role == 'office'
                              ? 'Office'
                              : auth.role == 'admin'
                                  ? 'Admin'
                                  : 'Account',
                          active: accountActive &&
                              auth.role != 'office' &&
                              auth.role != 'admin',
                          onTap: () {
                            final role = auth.role;
                            if (role == 'office' || role == 'admin') {
                              redirectAfterAuth(context, role ?? 'student', null);
                            } else {
                              openProtectedPage(
                                context,
                                builder: (_) => const SettingsPage(),
                                replace: _onPublicPeerPage,
                              );
                            }
                          },
                        ),
                        const Spacer(),
                        OutlinedButton(
                          onPressed: () async {
                            Navigator.pop(dialogContext);
                            await signOutToHome(context);
                          },
                          style: OutlinedButton.styleFrom(
                            foregroundColor: DesignTokens.maroon,
                            side: const BorderSide(color: DesignTokens.maroon),
                            minimumSize: const Size.fromHeight(48),
                            shape: const StadiumBorder(),
                          ),
                          child: const Text(
                            'Sign out',
                            style: TextStyle(fontWeight: FontWeight.w800),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
      },
      transitionBuilder: (context, animation, secondaryAnimation, child) {
        final slide = Tween<Offset>(
          begin: const Offset(1, 0),
          end: Offset.zero,
        ).animate(CurvedAnimation(parent: animation, curve: Curves.easeOutCubic));
        return SlideTransition(position: slide, child: child);
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

/// Shared control to return to the public homepage from KB / Ask / Tickets.
class PublicBackToHomeButton extends StatelessWidget {
  final Color foreground;
  final EdgeInsetsGeometry padding;

  const PublicBackToHomeButton({
    super.key,
    this.foreground = DesignTokens.maroon,
    this.padding = EdgeInsets.zero,
  });

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: TextButton.icon(
        onPressed: () => softPushAndClear(context, const StudentHomePage()),
        style: TextButton.styleFrom(
          foregroundColor: foreground,
          padding: padding,
          visualDensity: VisualDensity.compact,
          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        ),
        icon: Icon(Icons.arrow_back_rounded, size: 18, color: foreground),
        label: const Text(
          'Back to home',
          style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
        ),
      ),
    );
  }
}














