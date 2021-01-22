
function set_title(index, title) {
    var c = $('canvas.flot-base')[index];
    var canvas = c.getContext("2d");
    canvas.font = "12px sans-serif";
    canvas.textAlign = 'center';
    canvas.fillText(title, 120, 25);
}

$(function() {
    $("<div id='tooltip'></div>").css({
	position: "absolute",
	display: "none",
	border: "1px solid #fdd",
	padding: "2px",
	"background-color": "#ffffca",
	opacity: 0.80,
	"font-size": "0.75em"
    }).appendTo("body");

    $(".placeholder").bind("plothover", function (event, pos, item) {
	if (item) {
	    var x = item.datapoint[0].toFixed(2),
	    y = item.datapoint[1].toFixed(2);
	    $("#tooltip").html(item.series.label + ": " + y)
		.css({top: item.pageY+5, left: item.pageX+5})
		.fadeIn(200);
	} else {
	    $("#tooltip").hide();
	}
    });
});


