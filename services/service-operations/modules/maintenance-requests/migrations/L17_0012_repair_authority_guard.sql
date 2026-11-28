CREATE FUNCTION public.repair_job_authority_fence_v1() RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT to_regclass('public.service_job_authority_leases') IS NOT NULL
$$;
