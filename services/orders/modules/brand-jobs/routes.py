"""Framework-neutral private route adapter; mounting belongs to runtime composition."""

async def authorize_route(coordinator, command):
    try:
        result = await coordinator.authorize(command)
    except PermissionError:
        return 403, {'code': 'denied', 'message': {'en': 'Access denied.', 'ar': 'الوصول مرفوض.'}}
    except (TimeoutError, ConnectionError):
        return 503, {'code': 'unavailable', 'message': {
            'en': 'Current access is unavailable. Retry the same action reference.',
            'ar': 'التحقق من الوصول الحالي غير متاح. أعد المحاولة بمرجع الإجراء نفسه.'}}
    except ValueError:
        return 409, {'code': 'operation_conflict', 'message': {
            'en': 'This action reference has different content. Check the original action.',
            'ar': 'هذا المرجع مرتبط بمحتوى مختلف. تحقق من الإجراء الأصلي.'}}
    return {'authorized': 200, 'pending': 202, 'unavailable': 503, 'stale': 409, 'denied': 403}[result['state']], result


async def lookup_route(coordinator, command):
    try:
        result = await coordinator.lookup(command)
    except PermissionError:
        return 403, {'code': 'denied', 'message': {'en': 'Access denied.', 'ar': 'الوصول مرفوض.'}}
    except (TimeoutError, ConnectionError):
        return 503, {'code': 'unavailable', 'message': {
            'en': 'Current access is unavailable. Retry the same action reference.',
            'ar': 'التحقق من الوصول الحالي غير متاح. أعد المحاولة بمرجع الإجراء نفسه.'}}
    except ValueError:
        return 409, {'code': 'operation_conflict', 'message': {
            'en': 'Check the original action reference.', 'ar': 'تحقق من مرجع الإجراء الأصلي.'}}
    return {'authorized': 200, 'pending': 202, 'unavailable': 503, 'stale': 409, 'denied': 403}[result['state']], result
