# Horizontal bar chart with a deleted value axis

No corpus deck deletes the value axis of a horizontal bar chart, so there is no PowerPoint
render to compare; the behaviour is covered by
`test_a_deleted_horizontal_value_axis_draws_no_tick_labels`, which fails without the fix
(the numeric labels were still drawn along the bottom).
