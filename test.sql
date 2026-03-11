
--- Simples
SELECT 
    COUNT(*) AS total_linhas,
    MIN(l_shipdate) AS data_mais_antiga,
    MAX(l_shipdate) AS data_mais_recente
FROM lineitem
WHERE l_shipdate >= DATE '1995-01-01'
  AND l_shipdate < DATE '1996-01-01';

---simples
SELECT *
FROM lineitem
WHERE l_commitdate > l_shipdate;


--- intermediário

SELECT 
    p_type,
    AVG(l_extendedprice * (1 - l_discount)) AS preco_medio_descontado
FROM part
JOIN lineitem ON p_partkey = l_partkey
WHERE p_type LIKE 'STANDARD%'
  AND l_shipdate >= DATE '1995-01-01'
  AND l_shipdate <  DATE '1996-01-01'
GROUP BY p_type
ORDER BY preco_medio_descontado DESC
LIMIT 15;

--- intermediário
SELECT 
    o_orderkey,
    o_totalprice,
    o_orderpriority,
    o_clerk
FROM orders
ORDER BY o_totalprice DESC;

--- avançado
WITH top_customers AS (
    SELECT 
        c_custkey,
        SUM(o_totalprice) AS total_gasto
    FROM customer
    JOIN orders ON c_custkey = o_custkey
    WHERE o_orderdate >= DATE '1995-01-01'
      AND o_orderdate <  DATE '1996-01-01'
    GROUP BY c_custkey
    ORDER BY total_gasto DESC
    LIMIT 100
)
SELECT 
    c_name,
    c_nationkey,
    n_name,
    tc.total_gasto
FROM top_customers tc
JOIN customer c ON tc.c_custkey = c.c_custkey
JOIN nation n ON c.c_nationkey = n.n_nationkey
ORDER BY tc.total_gasto DESC;


--- avançado
SELECT 
    c_name,
    c_address,
    c_phone,
    c_comment,
    COUNT(*) AS qtde_pedidos,
    SUM(l_quantity) AS total_quantidade,
    SUM(l_extendedprice * (1 - l_discount)) AS receita_liquida
FROM customer
JOIN orders  ON c_custkey = o_custkey
JOIN lineitem ON o_orderkey = l_orderkey
WHERE l_receiptdate >= DATE '1994-01-01'
GROUP BY c_custkey, c_name, c_address, c_phone, c_comment
ORDER BY receita_liquida DESC;