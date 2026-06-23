# Brain Nodes Hotfix

Fixed Brain Nodes loading error:

```text
TypeError: BrainGraphBuilder.build() got an unexpected keyword argument 'max_nodes'
```

The graph builder now accepts both `limit` and `max_nodes`, so older/newer GUI calls remain compatible.

Checks performed:

- Python compile-check on all Python files
- BrainGraphBuilder smoke-test with `max_nodes`
- BrainGraphBuilder smoke-test with `limit`

No database changes are required.
