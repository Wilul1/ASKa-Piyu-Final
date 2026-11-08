import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/auth_models.dart';
import '../navigation/soft_page_route.dart';
import '../services/eye_comfort.dart';
import '../widgets/public_site_header.dart';
import 'chatbot_page.dart';
import 'knowledge_base_page.dart';
import 'my_tickets_page.dart';
import 'student_mailbox_page.dart';
import 'verify_email_page.dart';

const _navy = Color(0xFF1B2333);
const _muted = Color(0xFF6B7280);
const _pageBg = Color(0xFFF7F5F6);
const _cardLine = Color(0xFFE8EAEE);
const _iconWell = Color(0xFFF8E8EA);
const _hairline = Color(0xFFE6E8EE);
const _accountOuterPad = 40.0;
const _accountRailWidth = 200.0;

enum _AccountSection { account, help, about }

/// Account settings: profile, security, preferences, Eye Comfort, and sign-out.
class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});

  static String roleLabel(String role) {
    final normalized = role.trim().toLowerCase();
    switch (normalized) {
      case 'faculty':
        return 'Faculty';
      case 'student':
        return 'Student';
      case 'office':
        return 'Office staff';
      case 'admin':
        return 'Administrator';
      default:
        return role.trim().isEmpty ? 'User' : role.trim();
    }
  }

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  _AccountSection _section = _AccountSection.account;

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    final user = auth.currentUser;
    final eyeComfort = EyeComfortScope.isEnabled(context);
    final width = MediaQuery.sizeOf(context).width;
    final split = width >= 840;
    final headerPad = width * DesignTokens.kbDesktopSideInset;
    final pagePad = split
        ? _accountOuterPad
        : (width >= 600 ? 24.0 : 16.0);
    final leftPad = split ? headerPad : pagePad;
    final bg = eyeComfort ? EyeComfortColors.bg : _pageBg;
    final line = eyeComfort ? EyeComfortColors.border : _hairline;

    final sidebar = _AccountSideNav(
      section: _section,
      onSelect: (value) => setState(() => _section = value),
    );
    final main = user == null
        ? const _SettingsSignedOut()
        : switch (_section) {
            _AccountSection.account => _AccountMain(
                user: user,
                wide: split,
                onChangePassword: () => _showChangePasswordDialog(context),
                onSignOut: () => signOutToHome(context),
              ),
            _AccountSection.help => const _HelpSupportPanel(),
            _AccountSection.about => const _AboutPanel(),
          };

    return Scaffold(
      backgroundColor: bg,
      body: Column(
        children: [
          const PublicSiteHeader(accountActive: true),
          Expanded(
            child: user == null
                ? Center(child: main)
                : split
                    ? Row(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Padding(
                            padding: EdgeInsets.fromLTRB(
                              leftPad,
                              28,
                              12,
                              24,
                            ),
                            child: SizedBox(
                              width: _accountRailWidth,
                              child: sidebar,
                            ),
                          ),
                          Container(width: 1, color: line),
                          Expanded(
                            child: SingleChildScrollView(
                              padding: EdgeInsets.fromLTRB(
                                24,
                                22,
                                pagePad,
                                40,
                              ),
                              child: main,
                            ),
                          ),
                        ],
                      )
                    : SingleChildScrollView(
                        padding: EdgeInsets.fromLTRB(
                          pagePad,
                          20,
                          pagePad,
                          36,
                        ),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            sidebar,
                            const SizedBox(height: 20),
                            main,
                          ],
                        ),
                      ),
          ),
        ],
      ),
    );
  }

  Future<void> _showChangePasswordDialog(BuildContext context) async {
    final changed = await showDialog<bool>(
      context: context,
      builder: (_) => const _ChangePasswordDialog(),
    );
    if (changed == true && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Password updated.')),
      );
    }
  }
}

class _AccountSideNav extends StatelessWidget {
  final _AccountSection section;
  final ValueChanged<_AccountSection> onSelect;

  const _AccountSideNav({required this.section, required this.onSelect});

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _SideNavItem(
          icon: Icons.person_outline_rounded,
          label: 'Account',
          selected: section == _AccountSection.account,
          onTap: () => onSelect(_AccountSection.account),
        ),
        const SizedBox(height: 4),
        _SideNavItem(
          icon: Icons.help_outline_rounded,
          label: 'Help & Support',
          selected: section == _AccountSection.help,
          onTap: () => onSelect(_AccountSection.help),
        ),
        const SizedBox(height: 4),
        _SideNavItem(
          icon: Icons.info_outline_rounded,
          label: 'About ASKa-Piyu',
          selected: section == _AccountSection.about,
          onTap: () => onSelect(_AccountSection.about),
        ),
      ],
    );
  }
}

class _SideNavItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _SideNavItem({
    required this.icon,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final fg = selected ? Colors.white : const Color(0xFF6B7280);
    return Material(
      color: selected ? DesignTokens.maroon : Colors.transparent,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 11),
          child: Row(
            children: [
              Icon(icon, size: 16, color: fg),
              const SizedBox(width: 10),
              Flexible(
                child: Text(
                  label,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: fg,
                    fontWeight: FontWeight.w700,
                    fontSize: 13.5,
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

class _AccountMain extends StatelessWidget {
  final AuthUser user;
  final bool wide;
  final VoidCallback onChangePassword;
  final Future<void> Function() onSignOut;

  const _AccountMain({
    required this.user,
    required this.wide,
    required this.onChangePassword,
    required this.onSignOut,
  });

  @override
  Widget build(BuildContext context) {
    final security = _SecurityCard(
      user: user,
      onChangePassword: onChangePassword,
    );
    final preferences = const _PreferencesCard();
    final eyeComfort = const _EyeComfortCard();

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _SectionHeading(
          title: 'Account Settings',
          subtitle: 'Manage your account details, preferences, and security settings.',
        ),
        const SizedBox(height: 18),
        _ProfileCard(user: user),
        const SizedBox(height: 14),
        if (wide)
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: security),
              const SizedBox(width: 14),
              Expanded(child: preferences),
            ],
          )
        else ...[
          security,
          const SizedBox(height: 14),
          preferences,
        ],
        const SizedBox(height: 14),
        if (wide)
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: eyeComfort),
              const SizedBox(width: 14),
              const Expanded(child: SizedBox.shrink()),
            ],
          )
        else
          eyeComfort,
        const SizedBox(height: 14),
        _SignOutCard(onSignOut: onSignOut),
      ],
    );
  }
}

class _SectionHeading extends StatelessWidget {
  final String title;
  final String subtitle;

  const _SectionHeading({required this.title, required this.subtitle});

  @override
  Widget build(BuildContext context) {
    final ink = EyeComfortScope.isEnabled(context)
        ? EyeComfortColors.ink
        : _navy;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: TextStyle(
            fontSize: 30,
            height: 1.15,
            fontWeight: FontWeight.w800,
            color: ink,
            letterSpacing: -0.5,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          subtitle,
          style: const TextStyle(
            fontSize: 14.5,
            height: 1.4,
            color: _muted,
            fontWeight: FontWeight.w500,
          ),
        ),
        const SizedBox(height: 12),
        const Align(
          alignment: Alignment.centerLeft,
          child: SizedBox(
            width: 52,
            height: 3,
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: DesignTokens.maroon,
                borderRadius: BorderRadius.all(Radius.circular(2)),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _SettingsCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color? color;
  final Color? borderColor;

  const _SettingsCard({
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.color,
    this.borderColor,
  });

  @override
  Widget build(BuildContext context) {
    final eyeComfort = EyeComfortScope.isEnabled(context);
    return Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(
        color: color ??
            (eyeComfort ? EyeComfortColors.cardBg : Colors.white),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: borderColor ??
              (eyeComfort ? EyeComfortColors.border : _cardLine),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.03),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: child,
    );
  }
}

class _ProfileCard extends StatelessWidget {
  final AuthUser user;

  const _ProfileCard({required this.user});

  @override
  Widget build(BuildContext context) {
    final office = (user.officeName ?? '').trim();
    final stacked = MediaQuery.sizeOf(context).width < 700;
    final identity = Row(
      children: [
        Container(
          width: 56,
          height: 56,
          decoration: const BoxDecoration(
            color: Color(0xFFF3E4E6),
            shape: BoxShape.circle,
          ),
          child: const Icon(
            Icons.person_rounded,
            color: Color(0xFF9A6B72),
            size: 30,
          ),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                user.fullName,
                style: const TextStyle(
                  fontSize: 16.5,
                  fontWeight: FontWeight.w800,
                  color: _navy,
                ),
              ),
              const SizedBox(height: 6),
              _MetaLine(icon: Icons.mail_outline_rounded, text: user.email),
              const SizedBox(height: 4),
              _MetaLine(
                icon: Icons.school_outlined,
                text: SettingsPage.roleLabel(user.role),
              ),
              if (office.isNotEmpty) ...[
                const SizedBox(height: 4),
                _MetaLine(icon: Icons.apartment_outlined, text: office),
              ],
            ],
          ),
        ),
      ],
    );
    return _SettingsCard(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
      child: stacked
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                identity,
                const SizedBox(height: 14),
                Align(
                  alignment: Alignment.centerRight,
                  child: _EditProfileButton(user: user),
                ),
              ],
            )
          : Row(
              children: [
                Expanded(child: identity),
                const SizedBox(width: 12),
                _EditProfileButton(user: user),
              ],
            ),
    );
  }
}

class _MetaLine extends StatelessWidget {
  final IconData icon;
  final String text;

  const _MetaLine({required this.icon, required this.text});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 14, color: _muted),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            text,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: _muted,
              fontSize: 13,
              fontWeight: FontWeight.w500,
            ),
          ),
        ),
      ],
    );
  }
}

class _EditProfileButton extends StatelessWidget {
  final AuthUser user;

  const _EditProfileButton({required this.user});

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: () => _open(context),
      icon: const Icon(Icons.edit_outlined, size: 15),
      label: const Text('Edit Profile'),
      style: OutlinedButton.styleFrom(
        foregroundColor: DesignTokens.maroon,
        side: const BorderSide(color: Color(0xFFE4B4B8)),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
      ),
    );
  }

  Future<void> _open(BuildContext context) async {
    final result = await showDialog<String>(
      context: context,
      builder: (_) => _EditProfileDialog(user: user),
    );
    if (result == 'ticket' && context.mounted) {
      await openProtectedPage(
        context,
        builder: (_) => const MyTicketsPage(),
        requireVerifiedEmail: true,
        message: emailVerifyRequiredMessage,
      );
    }
  }
}

class _EditProfileDialog extends StatelessWidget {
  final AuthUser user;

  const _EditProfileDialog({required this.user});

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Edit Profile'),
      content: SizedBox(
        width: 360,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextFormField(
              initialValue: user.fullName,
              readOnly: true,
              decoration: const InputDecoration(labelText: 'Name'),
            ),
            const SizedBox(height: 12),
            TextFormField(
              initialValue: user.email,
              readOnly: true,
              decoration: const InputDecoration(labelText: 'Email'),
            ),
            const SizedBox(height: 12),
            Text(
              'Your registered name and email come from your campus account. '
              'Submit a support request if they need to be corrected.',
              style: TextStyle(color: DesignTokens.muted, fontSize: 13, height: 1.4),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop('ticket'),
          child: const Text('Submit a request'),
        ),
      ],
    );
  }
}

class _SecurityCard extends StatelessWidget {
  final AuthUser user;
  final VoidCallback onChangePassword;

  const _SecurityCard({required this.user, required this.onChangePassword});

  @override
  Widget build(BuildContext context) {
    return _SettingsCard(
      padding: const EdgeInsets.fromLTRB(18, 18, 10, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _CardIntro(
            icon: Icons.lock_outline_rounded,
            title: 'Security',
            subtitle: 'Keep your account safe and secure.',
          ),
          const SizedBox(height: 8),
          _ActionRow(
            icon: Icons.vpn_key_outlined,
            label: 'Change Password',
            onTap: onChangePassword,
          ),
          _ActionRow(
            icon: Icons.mail_outline_rounded,
            label: 'Email Verification',
            trailing: user.emailVerified
                ? const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.check_circle, size: 16, color: Color(0xFF16A34A)),
                      SizedBox(width: 6),
                      Text(
                        'Verified',
                        style: TextStyle(
                          color: Color(0xFF16A34A),
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  )
                : const Text(
                    'Pending',
                    style: TextStyle(
                      color: Color(0xFFB45309),
                      fontWeight: FontWeight.w700,
                      fontSize: 13,
                    ),
                  ),
            onTap: user.emailVerified
                ? null
                : () {
                    Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => const VerifyEmailPage(),
                      ),
                    );
                  },
            showDivider: false,
          ),
        ],
      ),
    );
  }
}

class _PreferencesCard extends StatelessWidget {
  const _PreferencesCard();

  @override
  Widget build(BuildContext context) {
    return _SettingsCard(
      padding: const EdgeInsets.fromLTRB(18, 18, 10, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _CardIntro(
            icon: Icons.settings_outlined,
            title: 'Preferences',
            subtitle: 'Customize your experience.',
          ),
          const SizedBox(height: 8),
          const _ActionRow(
            icon: Icons.palette_outlined,
            label: 'Theme',
            trailing: _FixedDropdown(value: 'Light'),
          ),
          const _ActionRow(
            icon: Icons.language_rounded,
            label: 'Language',
            trailing: _FixedDropdown(value: 'English'),
          ),
          _ActionRow(
            icon: Icons.notifications_none_rounded,
            label: 'Notifications',
            trailing: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Manage',
                  style: TextStyle(
                    color: DesignTokens.maroon,
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
                SizedBox(width: 2),
                Icon(
                  Icons.chevron_right_rounded,
                  color: DesignTokens.maroon,
                  size: 20,
                ),
              ],
            ),
            hideChevron: true,
            showDivider: false,
            onTap: () {
              openProtectedPage(
                context,
                builder: (_) => const StudentMailboxPage(),
                requireVerifiedEmail: true,
                message: emailVerifyRequiredMessage,
              );
            },
          ),
        ],
      ),
    );
  }
}

class _CardIntro extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;

  const _CardIntro({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            color: _iconWell,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Icon(icon, size: 18, color: DesignTokens.maroon),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                  color: _navy,
                ),
              ),
              Text(
                subtitle,
                style: const TextStyle(
                  fontSize: 12.5,
                  color: _muted,
                  height: 1.3,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ActionRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final Widget? trailing;
  final VoidCallback? onTap;
  final bool showDivider;
  final bool hideChevron;

  const _ActionRow({
    required this.icon,
    required this.label,
    this.trailing,
    this.onTap,
    this.showDivider = true,
    this.hideChevron = false,
  });

  @override
  Widget build(BuildContext context) {
    final row = Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Row(
        children: [
          Icon(icon, size: 18, color: const Color(0xFF7A838F)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              label,
              style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: _navy,
              ),
            ),
          ),
          if (trailing != null) trailing!,
          if (!hideChevron)
            const Icon(
              Icons.chevron_right_rounded,
              color: Color(0xFFB0B7C3),
              size: 20,
            ),
        ],
      ),
    );
    return Column(
      children: [
        Material(
          color: Colors.transparent,
          child: onTap == null
              ? row
              : InkWell(
                  onTap: onTap,
                  borderRadius: BorderRadius.circular(8),
                  child: row,
                ),
        ),
        if (showDivider) const Divider(height: 1, color: _cardLine),
      ],
    );
  }
}

class _FixedDropdown extends StatelessWidget {
  final String value;

  const _FixedDropdown({required this.value});

  @override
  Widget build(BuildContext context) {
    return DropdownButtonHideUnderline(
      child: DropdownButton<String>(
        value: value,
        isDense: true,
        borderRadius: BorderRadius.circular(10),
        icon: const Icon(
          Icons.keyboard_arrow_down_rounded,
          size: 18,
          color: _muted,
        ),
        style: const TextStyle(
          color: _muted,
          fontWeight: FontWeight.w600,
          fontSize: 13.5,
        ),
        items: [
          DropdownMenuItem<String>(value: value, child: Text(value)),
        ],
        onChanged: (_) {},
      ),
    );
  }
}

class _EyeComfortCard extends StatelessWidget {
  const _EyeComfortCard();

  @override
  Widget build(BuildContext context) {
    final enabled = EyeComfortScope.isEnabled(context);
    return _SettingsCard(
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: const BoxDecoration(
              color: Color(0xFF3A0A10),
              shape: BoxShape.circle,
            ),
            child: const Icon(
              Icons.nightlight_round,
              color: Color(0xFFF3D5D8),
              size: 20,
            ),
          ),
          const SizedBox(width: 12),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Eye Comfort',
                  style: TextStyle(
                    fontSize: 15.5,
                    fontWeight: FontWeight.w800,
                    color: _navy,
                  ),
                ),
                SizedBox(height: 2),
                Text(
                  'Reduce eye strain with warmer, softer colors.',
                  style: TextStyle(fontSize: 12.5, color: _muted, height: 1.3),
                ),
              ],
            ),
          ),
          Switch(
            value: enabled,
            onChanged: (value) =>
                EyeComfortScope.of(context).setEnabled(value),
            activeColor: DesignTokens.maroon,
            activeTrackColor: DesignTokens.maroon,
            inactiveTrackColor: const Color(0xFFE5E7EB),
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
          ),
        ],
      ),
    );
  }
}

class _SignOutCard extends StatelessWidget {
  final Future<void> Function() onSignOut;

  const _SignOutCard({required this.onSignOut});

  @override
  Widget build(BuildContext context) {
    final stacked = MediaQuery.sizeOf(context).width < 520;
    final copy = const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Sign out',
          style: TextStyle(
            fontSize: 15.5,
            fontWeight: FontWeight.w800,
            color: _navy,
          ),
        ),
        SizedBox(height: 2),
        Text(
          'End your session on this device.',
          style: TextStyle(fontSize: 12.5, color: _muted),
        ),
      ],
    );
    final button = ElevatedButton(
      onPressed: () => onSignOut(),
      style: ElevatedButton.styleFrom(
        backgroundColor: DesignTokens.maroon,
        foregroundColor: Colors.white,
        elevation: 0,
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
        shape: const StadiumBorder(),
      ),
      child: const Text(
        'Sign out',
        style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
      ),
    );
    return _SettingsCard(
      color: const Color(0xFFFDECEC),
      borderColor: const Color(0xFFF6C9CD),
      child: stacked
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(
                      Icons.logout_rounded,
                      color: DesignTokens.maroon,
                      size: 22,
                    ),
                    const SizedBox(width: 12),
                    Expanded(child: copy),
                  ],
                ),
                const SizedBox(height: 14),
                Align(alignment: Alignment.centerRight, child: button),
              ],
            )
          : Row(
              children: [
                const Icon(
                  Icons.logout_rounded,
                  color: DesignTokens.maroon,
                  size: 22,
                ),
                const SizedBox(width: 12),
                Expanded(child: copy),
                const SizedBox(width: 12),
                button,
              ],
            ),
    );
  }
}

class _HelpSupportPanel extends StatelessWidget {
  const _HelpSupportPanel();

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _SectionHeading(
          title: 'Help & Support',
          subtitle: 'Find guides, ask the assistant, or send a support ticket.',
        ),
        const SizedBox(height: 22),
        _HelpLinkCard(
          title: 'Knowledge Base',
          body: 'Browse official articles, policies, and campus procedures.',
          onTap: () => softPush(context, const KnowledgeBasePage()),
        ),
        const SizedBox(height: 12),
        _HelpLinkCard(
          title: 'Ask Assistant',
          body: 'Get answers from ASKa-Piyu using published campus sources.',
          onTap: () => softPush(context, const ChatbotPage()),
        ),
        const SizedBox(height: 12),
        _HelpLinkCard(
          title: 'My Tickets',
          body: 'Submit a request or track an existing support ticket.',
          onTap: () => openProtectedPage(
            context,
            builder: (_) => const MyTicketsPage(),
            requireVerifiedEmail: true,
            message: emailVerifyRequiredMessage,
          ),
        ),
        const SizedBox(height: 12),
        _HelpLinkCard(
          title: 'Mailbox',
          body: 'Read ticket replies, status changes, and other notifications.',
          onTap: () => openProtectedPage(
            context,
            builder: (_) => const StudentMailboxPage(),
            requireVerifiedEmail: true,
            message: emailVerifyRequiredMessage,
          ),
        ),
      ],
    );
  }
}

class _HelpLinkCard extends StatelessWidget {
  final String title;
  final String body;
  final VoidCallback onTap;

  const _HelpLinkCard({
    required this.title,
    required this.body,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: _SettingsCard(
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 15.5,
                        color: _navy,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      body,
                      style: const TextStyle(
                        color: _muted,
                        fontSize: 13,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded, color: Color(0xFFB0B7C3)),
            ],
          ),
        ),
      ),
    );
  }
}

class _AboutPanel extends StatelessWidget {
  const _AboutPanel();

  @override
  Widget build(BuildContext context) {
    return const Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _SectionHeading(
          title: 'About ASKa-Piyu',
          subtitle: 'Laguna State Polytechnic University student support.',
        ),
        SizedBox(height: 22),
        _SettingsCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'ASKa-Piyu helps students, faculty, and staff find official campus information and reach the right office for support.',
                style: TextStyle(fontSize: 14.5, height: 1.5, color: _navy),
              ),
              SizedBox(height: 12),
              Text(
                'Use the Knowledge Base for published guides, Ask Assistant for sourced answers, and My Tickets when you need a campus office to follow up.',
                style: TextStyle(fontSize: 14.5, height: 1.5, color: _muted),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _SettingsSignedOut extends StatelessWidget {
  const _SettingsSignedOut();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      constraints: const BoxConstraints(maxWidth: 560),
      margin: const EdgeInsets.all(24),
      padding: const EdgeInsets.all(28),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: DesignTokens.border),
      ),
      child: const Text(
        'Log in to manage your account settings.',
        style: TextStyle(color: DesignTokens.muted, height: 1.45),
      ),
    );
  }
}

class _ChangePasswordDialog extends StatefulWidget {
  const _ChangePasswordDialog();

  @override
  State<_ChangePasswordDialog> createState() => _ChangePasswordDialogState();
}

class _ChangePasswordDialogState extends State<_ChangePasswordDialog> {
  final _formKey = GlobalKey<FormState>();
  final _currentCtrl = TextEditingController();
  final _newCtrl = TextEditingController();
  final _confirmCtrl = TextEditingController();
  bool _loading = false;
  bool _obscureCurrent = true;
  bool _obscureNew = true;
  bool _obscureConfirm = true;
  String? _error;

  @override
  void dispose() {
    _currentCtrl.dispose();
    _newCtrl.dispose();
    _confirmCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await AuthScope.of(context).changePassword(
        ChangePasswordRequest(
          currentPassword: _currentCtrl.text,
          newPassword: _newCtrl.text,
        ),
      );
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _friendlyError(Object error) {
    final text = error.toString().replaceFirst('Bad state: ', '').trim();
    if (text.isEmpty) return 'Could not change password.';
    return text;
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Change password'),
      content: SizedBox(
        width: 360,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _currentCtrl,
                obscureText: _obscureCurrent,
                enabled: !_loading,
                decoration: InputDecoration(
                  labelText: 'Current password',
                  suffixIcon: IconButton(
                    onPressed: () =>
                        setState(() => _obscureCurrent = !_obscureCurrent),
                    icon: Icon(
                      _obscureCurrent
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined,
                    ),
                  ),
                ),
                validator: (value) {
                  if ((value ?? '').isEmpty) {
                    return 'Enter your current password.';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _newCtrl,
                obscureText: _obscureNew,
                enabled: !_loading,
                decoration: InputDecoration(
                  labelText: 'New password',
                  helperText:
                      'At least 10 characters, with a letter and a number.',
                  suffixIcon: IconButton(
                    onPressed: () => setState(() => _obscureNew = !_obscureNew),
                    icon: Icon(
                      _obscureNew
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined,
                    ),
                  ),
                ),
                validator: (value) {
                  final text = value ?? '';
                  if (text.isEmpty) return 'Enter a new password.';
                  if (text.length < 10) return 'Use at least 10 characters.';
                  if (!RegExp(r'[A-Za-z]').hasMatch(text)) {
                    return 'Include at least one letter.';
                  }
                  if (!RegExp(r'\d').hasMatch(text)) {
                    return 'Include at least one number.';
                  }
                  if (text == _currentCtrl.text) {
                    return 'New password must differ from the current one.';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _confirmCtrl,
                obscureText: _obscureConfirm,
                enabled: !_loading,
                decoration: InputDecoration(
                  labelText: 'Confirm new password',
                  suffixIcon: IconButton(
                    onPressed: () =>
                        setState(() => _obscureConfirm = !_obscureConfirm),
                    icon: Icon(
                      _obscureConfirm
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined,
                    ),
                  ),
                ),
                validator: (value) {
                  if (value != _newCtrl.text) return 'Passwords do not match.';
                  return null;
                },
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    _error!,
                    style: const TextStyle(color: Colors.red, fontSize: 13),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _loading ? null : () => Navigator.of(context).pop(false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: _loading ? null : _submit,
          child: _loading
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Update password'),
        ),
      ],
    );
  }
}
