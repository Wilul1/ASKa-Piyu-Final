import 'package:flutter/material.dart';

import '../design_tokens.dart';
import 'auth_split_shell.dart';

/// Simple sign-out confirmation dialog.
Future<bool> showSignOutConfirmDialog(BuildContext context) async {
  final confirmed = await showDialog<bool>(
    context: context,
    barrierDismissible: true,
    barrierColor: Colors.black.withValues(alpha: 0.45),
    builder: (dialogContext) => const SignOutConfirmDialog(),
  );
  return confirmed == true;
}

class SignOutConfirmDialog extends StatelessWidget {
  const SignOutConfirmDialog({super.key});

  static const _maroon = AuthSplitShell.maroon;

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final isNarrow = size.width < 520;
    final horizontalInset = isNarrow ? 20.0 : 48.0;
    final maxWidth = isNarrow ? size.width - (horizontalInset * 2) : 360.0;

    return Dialog(
      insetPadding: EdgeInsets.symmetric(
        horizontal: horizontalInset,
        vertical: isNarrow ? 24 : 40,
      ),
      backgroundColor: Colors.white,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: const BorderSide(color: Color(0xFFF0E4E6)),
      ),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: Padding(
          padding: EdgeInsets.fromLTRB(
            isNarrow ? 20 : 24,
            isNarrow ? 22 : 24,
            isNarrow ? 20 : 24,
            isNarrow ? 20 : 20,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Sign out?',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                  color: DesignTokens.ink,
                  height: 1.3,
                ),
              ),
              SizedBox(height: isNarrow ? 20 : 22),
              if (isNarrow) ...[
                _SignOutPrimaryButton(
                  onPressed: () => Navigator.of(context).pop(true),
                ),
                const SizedBox(height: 10),
                _SignOutSecondaryButton(
                  onPressed: () => Navigator.of(context).pop(false),
                ),
              ] else
                Row(
                  children: [
                    Expanded(
                      child: _SignOutSecondaryButton(
                        onPressed: () => Navigator.of(context).pop(false),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: _SignOutPrimaryButton(
                        onPressed: () => Navigator.of(context).pop(true),
                      ),
                    ),
                  ],
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SignOutPrimaryButton extends StatelessWidget {
  const _SignOutPrimaryButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 44,
      child: FilledButton(
        onPressed: onPressed,
        style: FilledButton.styleFrom(
          backgroundColor: SignOutConfirmDialog._maroon,
          foregroundColor: Colors.white,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
          textStyle: const TextStyle(
            fontWeight: FontWeight.w600,
            fontSize: 14,
          ),
        ),
        child: const Text('Sign out'),
      ),
    );
  }
}

class _SignOutSecondaryButton extends StatelessWidget {
  const _SignOutSecondaryButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 44,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          foregroundColor: SignOutConfirmDialog._maroon,
          side: const BorderSide(color: SignOutConfirmDialog._maroon),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
          textStyle: const TextStyle(
            fontWeight: FontWeight.w600,
            fontSize: 14,
          ),
        ),
        child: const Text('Cancel'),
      ),
    );
  }
}
