import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../services/auth_service.dart';
import '../widgets/auth_split_shell.dart';

class VerifyEmailPage extends StatefulWidget {
  final WidgetBuilder? returnTo;
  final String? gateRole;

  const VerifyEmailPage({
    super.key,
    this.returnTo,
    this.gateRole,
  });

  @override
  State<VerifyEmailPage> createState() => _VerifyEmailPageState();
}

class _VerifyEmailPageState extends State<VerifyEmailPage> {
  final _formKey = GlobalKey<FormState>();
  final _codeCtrl = TextEditingController();
  bool _loading = false;
  bool _resending = false;
  String? _error;
  String? _info;

  @override
  void dispose() {
    _codeCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _loading = true;
      _error = null;
      _info = null;
    });
    try {
      final user = await AuthScope.of(context).verifyEmail(_codeCtrl.text);
      if (!mounted) return;
      redirectAfterAuth(
        context,
        user.role,
        widget.returnTo,
        gateRole: widget.gateRole,
      );
    } on AuthRequestException catch (error) {
      if (!mounted) return;
      setState(() => _error = error.message);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _resend() async {
    setState(() {
      _resending = true;
      _error = null;
      _info = null;
    });
    try {
      final message = await AuthScope.of(context).resendVerification();
      if (!mounted) return;
      setState(() => _info = message);
    } on AuthRequestException catch (error) {
      if (!mounted) return;
      setState(() => _error = error.message);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _resending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    final email = auth.currentUser?.email ?? 'your email';

    return AuthSplitShell(
      form: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'VERIFY EMAIL',
              style: TextStyle(
                fontSize: 26,
                fontWeight: FontWeight.w900,
                color: AuthSplitShell.maroon,
                letterSpacing: 1.0,
              ),
            ),
            const SizedBox(height: 10),
            Text(
              'We sent a 6-digit code to $email. Enter it below to confirm this inbox is yours.',
              style: const TextStyle(
                color: Color(0xFF6B7280),
                height: 1.4,
                fontSize: 13,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              'If it is not in Inbox, check Spam or Promotions, then tap “Report not spam” so future codes land in Inbox.',
              style: TextStyle(
                color: Color(0xFF9CA3AF),
                height: 1.35,
                fontSize: 12,
              ),
            ),
            const SizedBox(height: 22),
            TextFormField(
              controller: _codeCtrl,
              keyboardType: TextInputType.number,
              textInputAction: TextInputAction.done,
              onFieldSubmitted: (_) => _submit(),
              inputFormatters: [
                FilteringTextInputFormatter.digitsOnly,
                LengthLimitingTextInputFormatter(6),
              ],
              validator: (value) {
                final text = (value ?? '').trim();
                if (text.length != 6) return 'Enter the 6-digit code.';
                return null;
              },
              decoration: authFieldDecoration('Verification code'),
            ),
            if (_error != null) ...[
              const SizedBox(height: 14),
              AuthErrorBanner(message: _error!),
            ],
            if (_info != null) ...[
              const SizedBox(height: 14),
              Text(
                _info!,
                style: const TextStyle(
                  color: Color(0xFF166534),
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
            const SizedBox(height: 20),
            AuthPrimaryButton(
              label: 'VERIFY',
              loading: _loading,
              onPressed: _submit,
            ),
            const SizedBox(height: 16),
            TextButton(
              onPressed: (_loading || _resending) ? null : _resend,
              child: Text(
                _resending ? 'Sending…' : 'Resend code',
                style: const TextStyle(
                  color: AuthSplitShell.maroon,
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

String _friendlyError(Object error) {
  final text = error.toString().replaceFirst('Bad state: ', '').trim();
  return text.isEmpty ? 'Something went wrong. Please try again.' : text;
}
