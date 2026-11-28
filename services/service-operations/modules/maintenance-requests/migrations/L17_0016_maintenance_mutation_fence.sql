CREATE FUNCTION public.maintenance_request_authority_fence_v1() RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT to_regclass('public.service_maintenance_request_leases') IS NOT NULL;
$$;
