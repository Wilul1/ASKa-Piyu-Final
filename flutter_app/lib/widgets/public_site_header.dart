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
import '../screens/student_mailbox_page.dart';
import '../services/eye_comfort.dart';
import 'phone_layout.dart';

/// Shared top navigation for public landing / Knowledge Base (no sidebar).
class PublicSiteHeader extends StatelessWidget {
  final bool knowledgeBaseActive;
  final bool askAssistantActive;
  final bool myTicketsActive;
  final bool mailboxActive;
  final bool accountActive;
  final bool slim;

  /// True only on the homepage, where a decorative wave is painted behind
  /// this header (see `_TopBrandWavePainter` in student_home.dart) and
  /// needs to show through instead of being covered by an opaque white
  /// background. Every other caller omits this and keeps the original
  /// solid-white navbar unchanged.
  final bool transparentBackground;

  const PublicSiteHeader({
    super.key,
    this.knowledgeBaseActive = false,
    this.askAssistantActive = false,
    this.myTicketsActive = false,
    this.mailboxActive = false,
    this.accountActive = false,
    this.slim = false,
    this.transparentBackground = false,
  });

  bool get _onPublicPeerPage =>
      knowledgeBaseActive ||
      askAssistantActive ||
      myTicketsActive ||
      mailboxActive ||
      accountActive;

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
    final auth = AuthScope.of(context);
    final isAuthed = auth.isAuthenticated;
    final role = auth.role;
    // An authenticated student/faculty desktop nav has one more link
    // (Mailbox) than every other case (logged out, or office/admin, who
    // never see it) -- confirmed by direct measurement that the full row
    // then needs ~1101px of content width (page width minus the 32px*2
    // horizontal padding) before it stops overflowing. Only widen the
    // breakpoint for the case that actually needs it, so a logged-out
    // visitor or office/admin user isn't pushed into mobile mode any
    // earlier than before.
    final showsMailboxLink = isAuthed && role != 'office' && role != 'admin';
    final isNarrow = width < (showsMailboxLink ? 1140 : kPhoneLayoutBreakpoint);

    final eyeComfort = EyeComfortScope.isEnabled(context);

    // Matched chrome: the compact icon+label nav used on the inner app
    // pages (KB / My Tickets / Ask Assistant / Mailbox / Account), which
    // share the Knowledge Base column's side inset and let the page's own
    // (possibly eye-comfort) background show through instead of painting
    // a separate header color. The plain homepage nav below is unchanged.
    final matchedChrome = knowledgeBaseActive ||
        myTicketsActive ||
        askAssistantActive ||
        mailboxActive ||
        accountActive;
    final matchedNav = matchedChrome && !isNarrow;
    final kbSide = width * DesignTokens.kbDesktopSideInset;
    final kbLeft = matchedNav ? kbSide : (isNarrow ? 12.0 : 32.0);
    final kbRight = matchedNav ? kbSide : kbLeft;

    return Material(
      color: transparentBackground || matchedChrome
          ? Colors.transparent
          : (eyeComfort ? EyeComfortColors.headerBg : Colors.white),
      child: Container(
        decoration: transparentBackground || matchedChrome
            ? null
            : const BoxDecoration(
                border: Border(bottom: BorderSide(color: Color(0xFFEEF1F5))),
              ),
        padding: EdgeInsets.fromLTRB(
          kbLeft,
          // Desktop-only bump so the homepage's larger hero doesn't sit
          // under a comparatively tiny navbar -- narrow/slim values are
          // untouched since other public pages rely on them as-is.
          isNarrow ? (slim ? 8 : 14) : 18,
          kbRight,
          isNarrow ? (slim ? 8 : 14) : (matchedChrome ? 14 : 18),
        ),
        child: Center(
          child: ConstrainedBox(
            constraints: BoxConstraints(
              maxWidth: matchedNav ? double.infinity : kHomeContentMaxWidth,
            ),
            child: Row(
              children: [
                // Static branding, not a navigation control: previously an
                // InkWell that pushed the homepage, which made the brand
                // behave (and look, via its click cursor/ink splash) like a
                // link. Product decision is that the brand mark is purely
                // decorative, so it's now a plain, non-interactive Row --
                // `excludeSemantics` presents it as a single labeled
                // branding node rather than a tappable control.
                Semantics(
                  label: 'ASKa-Piyu',
                  container: true,
                  excludeSemantics: true,
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      BrandMark(
                        height: isNarrow
                            ? (slim ? 28 : 36)
                            : (matchedChrome ? 34 : 42),
                      ),
                      const SizedBox(width: 10),
                      Text(
                        slim && isNarrow && askAssistantActive
                            ? 'Ask Assistant'
                            : 'ASKa-Piyu',
                        style: TextStyle(
                          color: DesignTokens.maroon,
                          fontWeight: matchedChrome
                              ? FontWeight.w800
                              : FontWeight.w900,
                          fontSize: isNarrow
                              ? (slim ? 15 : 18)
                              : (matchedChrome ? 18 : 20),
                          letterSpacing: -0.2,
                          height: 1,
                        ),
                      ),
                    ],
                  ),
                ),
                const Spacer(),
                if (matchedNav)
                  Flexible(
                    child: Align(
                      alignment: Alignment.centerRight,
                      child: SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            _MatchedNavLink(
                              label: 'Knowledge Base',
                              icon: Icons.home,
                              active: knowledgeBaseActive,
                              iconTooltip: 'Home',
                              onIconTap: () => _goHome(context),
                              onTap: () {
                                if (knowledgeBaseActive) return;
                                _goPeer(context, const KnowledgeBasePage());
                              },
                            ),
                            _MatchedNavLink(
                              label: 'Ask Assistant',
                              icon: Icons.support_agent_outlined,
                              active: askAssistantActive,
                              onTap: () {
                                if (askAssistantActive) return;
                                _goPeer(context, const ChatbotPage());
                              },
                            ),
                            _MatchedNavLink(
                              label: 'My Tickets',
                              icon: Icons.mail_outline_rounded,
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
                            if (showsMailboxLink)
                              _MatchedNavLink(
                                label: 'Mailbox',
                                icon: Icons.inbox_outlined,
                                active: mailboxActive,
                                onTap: () {
                                  if (mailboxActive) return;
                                  openProtectedPage(
                                    context,
                                    builder: (_) => const StudentMailboxPage(),
                                    replace: _onPublicPeerPage,
                                    requireVerifiedEmail: true,
                                    message: emailVerifyRequiredMessage,
                                  );
                                },
                              ),
                            _MatchedNavLink(
                              label: !isAuthed
                                  ? 'Login'
                                  : role == 'office'
                                  ? 'Office'
                                  : role == 'admin'
                                  ? 'Admin'
                                  : 'Account',
                              icon: Icons.account_circle_outlined,
                              active: accountActive &&
                                  role != 'office' &&
                                  role != 'admin',
                              onTap: () {
                                if (!isAuthed) {
                                  softPush(context, const LoginPage());
                                } else if (role == 'office' ||
                                    role == 'admin') {
                                  redirectAfterAuth(
                                    context,
                                    role ?? 'student',
                                    null,
                                  );
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
                          ],
                        ),
                      ),
                    ),
                  )
                else if (!isNarrow) ...[
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
                  if (showsMailboxLink)
                    _NavLink(
                      label: 'Mailbox',
                      active: mailboxActive,
                      onTap: () {
                        if (mailboxActive) return;
                        openProtectedPage(
                          context,
                          builder: (_) => const StudentMailboxPage(),
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
                      label:
                          role == 'office'
                              ? 'Office'
                              : role == 'admin'
                              ? 'Admin'
                              : 'Account',
                      active:
                          accountActive && role != 'office' && role != 'admin',
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
                if (!matchedChrome && !isAuthed && !isNarrow)
                  ElevatedButton(
                    onPressed: () => softPush(context, const SignupPage()),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF5C0A0F),
                      foregroundColor: Colors.white,
                      elevation: 0,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 20,
                        vertical: 14,
                      ),
                      shape: const StadiumBorder(),
                    ),
                    child: const Text(
                      'Sign up',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                  ),
                // No "Sign out" button here -- Account already has one
                // (SettingsPage's own Sign out row), and showing a second,
                // independent control for the same action in every shared
                // public/student header was redundant. Office/admin keep
                // their own, separate sign-out on their sidebar shell,
                // untouched by this.
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
                    icon: const Icon(
                      Icons.menu_rounded,
                      color: DesignTokens.maroon,
                    ),
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
    final drawerWidth =
        width < 360 ? width * 0.92 : (width * 0.82).clamp(260.0, 320.0);

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
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 12,
                ),
                child: Row(
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        color:
                            active
                                ? DesignTokens.maroon
                                : const Color(0xFFD1D5DB),
                        borderRadius: BorderRadius.circular(2),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        label,
                        style: TextStyle(
                          fontWeight:
                              active ? FontWeight.w800 : FontWeight.w700,
                          color:
                              active
                                  ? DesignTokens.maroon
                                  : const Color(0xFF374151),
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
                      if (auth.isAuthenticated &&
                          auth.role != 'office' &&
                          auth.role != 'admin')
                        item(
                          label: 'Mailbox',
                          active: mailboxActive,
                          onTap: () {
                            openProtectedPage(
                              context,
                              builder: (_) => const StudentMailboxPage(),
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
                          label:
                              auth.role == 'office'
                                  ? 'Office'
                                  : auth.role == 'admin'
                                  ? 'Admin'
                                  : 'Account',
                          active:
                              accountActive &&
                              auth.role != 'office' &&
                              auth.role != 'admin',
                          onTap: () {
                            final role = auth.role;
                            if (role == 'office' || role == 'admin') {
                              redirectAfterAuth(
                                context,
                                role ?? 'student',
                                null,
                              );
                            } else {
                              openProtectedPage(
                                context,
                                builder: (_) => const SettingsPage(),
                                replace: _onPublicPeerPage,
                              );
                            }
                          },
                        ),
                        // No "Sign out" here either -- same reasoning as
                        // the desktop nav above: Account already has one.
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
        ).animate(
          CurvedAnimation(parent: animation, curve: Curves.easeOutCubic),
        );
        return SlideTransition(position: slide, child: child);
      },
    );
  }
}

/// Shared ASKa-Piyu brand mark: the one logo rendering used on every page
/// that shows it (public header, chatbot empty-state greeting). Always
/// solid black, always cropped -- there is no second "uncropped, full
/// color" variant.
///
/// `brandmark.png` is 777x457. The mark itself is about x=218-487,
/// y=122-330. Faint full-width hairlines sit on y=0-4 and y=448-456 and
/// read as a box and an underline once the file is scaled into the header,
/// so every caller clips them via the same window below, which keeps a few
/// pixels of padding around the mark and leaves its proportions unchanged.
class BrandMark extends StatelessWidget {
  final double height;

  const BrandMark({super.key, required this.height});

  @override
  Widget build(BuildContext context) {
    return ColorFiltered(
      colorFilter: const ColorFilter.mode(Colors.black, BlendMode.srcIn),
      child: ClipRect(
        child: Align(
          alignment: const Alignment(-0.0927, -0.0109),
          widthFactor: 282 / 777,
          heightFactor: 221 / 457,
          child: Image.asset(
            'assets/brandmark.png',
            height: height,
            fit: BoxFit.contain,
            filterQuality: FilterQuality.high,
            gaplessPlayback: true,
          ),
        ),
      ),
    );
  }
}

/// Matched-chrome header item: icon and label sit on one line, and the
/// active underline matches the label width only.
class _MatchedNavLink extends StatelessWidget {
  final String label;
  final VoidCallback onTap;
  final bool active;
  final IconData? icon;
  final String? iconTooltip;
  final VoidCallback? onIconTap;

  const _MatchedNavLink({
    required this.label,
    required this.onTap,
    this.active = false,
    this.icon,
    this.iconTooltip,
    this.onIconTap,
  });

  @override
  Widget build(BuildContext context) {
    final color = active ? DesignTokens.maroon : const Color(0xFF3E4654);
    final labelStyle = TextStyle(
      color: color,
      fontWeight: active ? FontWeight.w700 : FontWeight.w600,
      fontSize: 14.5,
      height: 1.1,
    );

    final labelWidget = Stack(
      clipBehavior: Clip.none,
      children: [
        Text(label, style: labelStyle),
        if (active)
          Positioned(
            left: 0,
            right: 0,
            bottom: -8,
            child: Container(
              height: 2.5,
              decoration: BoxDecoration(
                color: DesignTokens.maroon,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
      ],
    );

    return Padding(
      padding: const EdgeInsets.only(left: 14),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          if (icon != null) ...[
            _NavIconButton(
              icon: icon!,
              size: 16,
              tooltip: onIconTap == null ? label : (iconTooltip ?? label),
              onTap: onIconTap ?? onTap,
            ),
            const SizedBox(width: 6),
          ],
          TextButton(
            onPressed: onTap,
            style: TextButton.styleFrom(
              foregroundColor: color,
              padding: EdgeInsets.zero,
              minimumSize: Size.zero,
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
            child: labelWidget,
          ),
        ],
      ),
    );
  }
}

class _NavIconButton extends StatelessWidget {
  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;
  final double size;

  const _NavIconButton({
    required this.icon,
    required this.tooltip,
    required this.onTap,
    this.size = 17,
  });

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(6),
        child: Icon(
          icon,
          size: size,
          color: const Color(0xFF000000),
        ),
      ),
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
        foregroundColor: active ? DesignTokens.maroon : const Color(0xFF4B5563),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      ),
      // IntrinsicWidth so the active underline matches the text's own
      // width rather than the button's full hit-target width; a fixed-
      // height SizedBox in the inactive case keeps every nav item the
      // same height regardless of active state.
      child: IntrinsicWidth(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              label,
              style: TextStyle(
                fontWeight: active ? FontWeight.w900 : FontWeight.w700,
                fontSize: 14,
              ),
            ),
            const SizedBox(height: 4),
            if (active)
              Container(height: 2, color: DesignTokens.maroon)
            else
              const SizedBox(height: 2),
          ],
        ),
      ),
    );
  }
}

/// Shared control to return to the public homepage from KB / Ask / Tickets.
class PublicBackToHomeButton extends StatelessWidget {
  final Color foreground;
  final Color? labelColor;
  final EdgeInsetsGeometry padding;

  const PublicBackToHomeButton({
    super.key,
    this.foreground = DesignTokens.maroon,
    this.labelColor,
    this.padding = EdgeInsets.zero,
  });

  @override
  Widget build(BuildContext context) {
    final textColor = labelColor ?? foreground;
    return Align(
      alignment: Alignment.centerLeft,
      child: TextButton.icon(
        onPressed: () => softPushAndClear(context, const StudentHomePage()),
        style: TextButton.styleFrom(
          foregroundColor: textColor,
          padding: padding,
          visualDensity: VisualDensity.compact,
          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        ),
        icon: Icon(Icons.arrow_back_rounded, size: 18, color: foreground),
        label: Text(
          'Back to home',
          style: TextStyle(
            fontWeight: FontWeight.w700,
            fontSize: 13.5,
            color: textColor,
          ),
        ),
      ),
    );
  }
}
